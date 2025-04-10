from .models import Receipt, Category, ReceiptItem, GroupMember, ReceiptItemSplit, Debt
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from calendar import monthrange
from django.db.models import Sum
from django.core.paginator import Paginator
from django.urls import reverse
from django.db.models import Sum, Q


# Helper function to validate the receipt data
def validate_receipt_data(receipt_data):
    required_fields = ['name', 'total_amount', 'subtotal', 'tax_amount', 'tax_rate',
                       'discount_amount', 'discount_rate', 'purchase_date', 'items']
    for field in required_fields:
        if field not in receipt_data:
            return False, f"Missing required field: {field}"

    items_data = receipt_data.get('items', [])
    if not items_data:
        return False, "At least one item is required."

    for item in items_data:
        if 'split_method' not in item:
            return False, "Each item must have a split_method."
        if item['split_method'] not in ['EVENLY', 'BY_USER']:
            return False, f"Invalid split_method: {item['split_method']}"
        if item['split_method'] == 'BY_USER':
            if 'split_user_id' not in item:
                return False, "split_user_id is required for BY_USER split method."
        if 'paid_by_id' not in item:
            return False, "paid_by_id is required for each item."

    return True, None


# Helper function to create the receipt
def create_receipt(group, receipt_data, user):
    return Receipt.objects.create(
        group=group,
        name=receipt_data.get('name'),
        total_amount=Decimal(str(receipt_data.get('total_amount', 0.0))),
        subtotal=Decimal(str(receipt_data.get('subtotal', 0.0))),
        tax_amount=Decimal(str(receipt_data.get('tax_amount', 0.0))),
        tax_rate=Decimal(str(receipt_data.get('tax_rate', 0.0))),
        discount_amount=Decimal(str(receipt_data.get('discount_amount', 0.0))),
        discount_rate=Decimal(str(receipt_data.get('discount_rate', 0.0))),
        purchase_date=datetime.strptime(
            receipt_data.get('purchase_date'), '%Y-%m-%d').date(),
        uploaded_by=user,
        error=receipt_data.get('error')
    )


# Helper function to create a receipt item and its splits
def create_receipt_item_and_splits(receipt, item_data, group_members, group):
    # Find or create the category
    category_name = item_data.get('category')
    category = Category.objects.filter(group=group, name=category_name).first()
    if not category:
        category = Category.objects.create(group=group, name=category_name)

    # Create the ReceiptItem
    receipt_item = ReceiptItem.objects.create(
        receipt=receipt,
        category=category,
        name=item_data.get('name'),
        general_name=item_data.get('general_name'),
        quantity=float(item_data.get('quantity', 1.0)),
        price=Decimal(str(item_data.get('price', 0.0))),
        actual_price=Decimal(
            str(item_data.get('actual_price', item_data.get('price', 0.0))))
    )

    # Handle splitting
    split_method = item_data.get('split_method')
    paid_by = get_object_or_404(
        GroupMember, id=item_data.get('paid_by_id'), group=group)

    if split_method == 'EVENLY':
        num_members = group_members.count()
        if num_members == 0:
            raise ValueError("No members in the group to split the item.")
        split_amount = receipt_item.actual_price / num_members
        for member in group_members:
            ReceiptItemSplit.objects.create(
                receipt_item=receipt_item,
                group_member=member,
                amount=split_amount.quantize(Decimal('0.01')),
                paid_by=paid_by
            )
    elif split_method == 'BY_USER':
        split_user = get_object_or_404(
            GroupMember, id=item_data.get('split_user_id'), group=group)
        ReceiptItemSplit.objects.create(
            receipt_item=receipt_item,
            group_member=split_user,
            amount=receipt_item.actual_price,
            paid_by=paid_by
        )

    return receipt_item


# Helper function to update debts based on splits
def update_debts(splits, group):
    for split in splits:
        debtor = split.group_member
        creditor = split.paid_by
        amount = split.amount

        if debtor == creditor:
            continue  # No debt if the debtor and creditor are the same

        # Check for an existing debt from debtor to creditor
        debt = Debt.objects.filter(
            group=group, debtor=debtor, creditor=creditor).first()
        if debt:
            debt.amount += amount
            if debt.amount == 0:
                debt.delete()
            else:
                debt.save()
        else:
            # Check for a reverse debt (creditor owes debtor)
            reverse_debt = Debt.objects.filter(
                group=group, debtor=creditor, creditor=debtor).first()
            if reverse_debt:
                reverse_debt.amount -= amount
                if reverse_debt.amount == 0:
                    reverse_debt.delete()
                elif reverse_debt.amount < 0:
                    # Reverse the debt direction
                    Debt.objects.create(
                        group=group,
                        debtor=debtor,
                        creditor=creditor,
                        amount=-reverse_debt.amount
                    )
                    reverse_debt.delete()
                else:
                    reverse_debt.save()
            else:
                # Create a new debt
                Debt.objects.create(
                    group=group,
                    debtor=debtor,
                    creditor=creditor,
                    amount=amount
                )


def validate_year_and_month(year, month):
    try:
        year = int(year)
        month = int(month)
        if not (1 <= month <= 12):
            return False, "Month must be between 1 and 12."
        if year < 1900 or year > 9999:
            return False, "Year must be between 1900 and 9999."
        return True, (year, month)
    except ValueError:
        return False, "Invalid year or month format."


def get_date_range_for_month(year, month):
    start_date = datetime(year, month, 1).date()
    last_day = monthrange(year, month)[1]
    end_date = datetime(year, month, last_day).date()
    return start_date, end_date


def calculate_total_expense_for_member(member, start_date, end_date):
    return ReceiptItemSplit.objects.filter(
        group_member=member,
        receipt_item__receipt__purchase_date__range=(start_date, end_date)
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def calculate_seven_day_expenses(member, today):
    seven_days_ago = today - timedelta(days=6)
    expenses = []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        total = ReceiptItemSplit.objects.filter(
            group_member=member,
            receipt_item__receipt__purchase_date=day
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expenses.append({
            "date": day,
            "total_expense": total
        })
    return expenses


def calculate_monthly_expenses(member, current_date, num_months=12):
    expenses = []
    for i in range(num_months):
        # First day of current month
        target_date = current_date - timedelta(days=current_date.day - 1)
        target_date = target_date - timedelta(days=30 * i)  # Go back i months
        start_of_month = target_date.replace(day=1)
        last_day_of_month = monthrange(target_date.year, target_date.month)[1]
        end_of_month = target_date.replace(day=last_day_of_month)
        total = ReceiptItemSplit.objects.filter(
            group_member=member,
            receipt_item__receipt__purchase_date__range=(
                start_of_month, end_of_month)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expenses.append({
            "year": target_date.year,
            "month": target_date.month,
            "total_expense": total
        })
    return expenses


def calculate_category_expenses(member, group, start_date, end_date):
    expenses = []
    categories = Category.objects.filter(group=group)
    for category in categories:
        total = ReceiptItemSplit.objects.filter(
            group_member=member,
            receipt_item__category=category,
            receipt_item__receipt__purchase_date__range=(start_date, end_date)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if total > 0:
            expenses.append({
                "category": category,
                "total_expense": total
            })
    return expenses


def calculate_daily_expenses(member, start_date, end_date):
    expenses = []
    current_date = start_date
    while current_date <= end_date:
        total = ReceiptItemSplit.objects.filter(
            group_member=member,
            receipt_item__receipt__purchase_date=current_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expenses.append({
            "date": current_date,
            "total_expense": total
        })
        current_date += timedelta(days=1)
    return expenses


def calculate_group_expenses(group, start_date, end_date):
    total = ReceiptItemSplit.objects.filter(
        receipt_item__receipt__group=group,
        receipt_item__receipt__purchase_date__range=(start_date, end_date)
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    members = GroupMember.objects.filter(group=group)
    member_expenses = []
    for member in members:
        total_expense = calculate_total_expense_for_member(
            member, start_date, end_date)
        member_expenses.append({
            "group_member": member,
            "total_expense": total_expense
        })
    member_expenses.sort(key=lambda x: x['total_expense'], reverse=True)
    return total, member_expenses


def validate_payment_amount(payment_amount, debt_amount):
    try:
        # Convert to Decimal and round to 2 decimal places
        payment_amount = Decimal(str(payment_amount)).quantize(
            Decimal('0.00'),  # Round to 2 decimal places
            rounding=ROUND_HALF_UP  # Standard rounding (e.g., 1.235 → 1.24)
        )

        debt_amount = Decimal(str(debt_amount))

        print("payment_amount (rounded):", payment_amount)
        print("debt_amount:", debt_amount)
        if payment_amount <= 0:
            return False, "Payment amount must be greater than 0."
        if payment_amount > debt_amount:
            return False, "Payment amount cannot exceed the debt amount."
        return True, payment_amount
    except (TypeError, ValueError):
        return False, "Invalid payment amount."


def sort_debts(debts, user_member):
    """
    Sorts debts so that debts related to the user come first, then sorts by amount (descending).
    Args:
        debts: Queryset of Debt objects.
        user_member: The GroupMember object for the authenticated user.
    Returns:
        A sorted list of Debt objects.
    """
    debt_list = list(debts)
    debt_list.sort(key=lambda debt: (
        # First, sort by related_to_me (False comes after True, so we negate it)
        -(debt.debtor == user_member or debt.creditor == user_member),
        # Then, sort by amount (descending)
        -debt.amount
    ))
    return debt_list


def validate_history_params(request):
    """
    Validates query parameters for the history view.
    Returns a tuple (is_valid, result) where result is either an error message or a dict of validated params.
    """
    params = {
        'view': request.query_params.get('view', 'my_items'),
        'sort_by': request.query_params.get('sort_by', 'purchase_date'),
        'sort_order': request.query_params.get('sort_order', 'asc'),
        'search': request.query_params.get('search', ''),
        'category_id': request.query_params.get('category_id'),
        'page': request.query_params.get('page', '1'),
        'page_size': request.query_params.get('page_size', '20')
    }

    # Validate view
    if params['view'] not in ['my_items', 'group_items']:
        return False, "Invalid view parameter. Must be 'my_items' or 'group_items'."

    # Validate sort_by
    if params['sort_by'] not in ['purchase_date', 'price', 'quantity']:
        return False, "Invalid sort_by parameter. Must be 'purchase_date', 'price', or 'quantity'."

    # Validate sort_order
    if params['sort_order'] not in ['asc', 'desc']:
        return False, "Invalid sort_order parameter. Must be 'asc' or 'desc'."

    # Validate page and page_size
    try:
        params['page'] = int(params['page'])
        params['page_size'] = int(params['page_size'])
        if params['page'] < 1:
            return False, "Page number must be at least 1."
        if params['page_size'] < 1 or params['page_size'] > 100:
            return False, "Page size must be between 1 and 100."
    except ValueError:
        return False, "Page and page_size must be integers."

    return True, params


def fetch_base_items(group, user_member, view):
    """
    Fetches the initial queryset based on the view type.
    Args:
        group: The Group object.
        user_member: The GroupMember object for the authenticated user.
        view: 'my_items' or 'group_items'.
    Returns:
        Queryset of ReceiptItemSplit (for my_items) or ReceiptItem (for group_items).
    """
    if view == 'my_items':
        return ReceiptItemSplit.objects.filter(
            group_member=user_member,
            receipt_item__receipt__group=group
        ).select_related('receipt_item__receipt', 'receipt_item__category')
    else:
        return ReceiptItem.objects.filter(
            receipt__group=group
        ).select_related('receipt', 'category')


def apply_search_filter(items, view, search):
    """
    Applies the search filter to the queryset.
    Args:
        items: Queryset of ReceiptItemSplit or ReceiptItem objects.
        view: 'my_items' or 'group_items'.
        search: The search term.
    Returns:
        Filtered queryset.
    """
    if not search:
        return items

    if view == 'my_items':
        return items.filter(
            Q(receipt_item__name__icontains=search) |
            Q(receipt_item__general_name__icontains=search) |
            Q(receipt_item__receipt__name__icontains=search)
        )
    else:
        return items.filter(
            Q(name__icontains=search) |
            Q(general_name__icontains=search) |
            Q(receipt__name__icontains=search)
        )


def apply_category_filter(items, view, category_id):
    """
    Applies the category filter to the queryset.
    Args:
        items: Queryset of ReceiptItemSplit or ReceiptItem objects.
        view: 'my_items' or 'group_items'.
        category_id: The ID of the category to filter by.
    Returns:
        Filtered queryset.
    """
    if not category_id:
        return items

    if view == 'my_items':
        return items.filter(receipt_item__category_id=category_id)
    else:
        return items.filter(category_id=category_id)


def apply_sorting(items, view, sort_by, sort_order):
    """
    Applies sorting to the queryset.
    Args:
        items: Queryset of ReceiptItemSplit or ReceiptItem objects.
        view: 'my_items' or 'group_items'.
        sort_by: 'purchase_date', 'price', or 'quantity'.
        sort_order: 'asc' or 'desc'.
    Returns:
        Sorted queryset.
    """
    sort_field_map = {
        'purchase_date': 'receipt_item__receipt__purchase_date' if view == 'my_items' else 'receipt__purchase_date',
        'price': 'receipt_item__price' if view == 'my_items' else 'price',
        'quantity': 'receipt_item__quantity' if view == 'my_items' else 'quantity'
    }
    sort_field = sort_field_map[sort_by]
    if sort_order == 'desc':
        sort_field = f'-{sort_field}'
    return items.order_by(sort_field)


def calculate_summary_stats(items, view):
    """
    Calculates total_items and total_spent for the queryset.
    Args:
        items: Queryset of ReceiptItemSplit or ReceiptItem objects.
        view: 'my_items' or 'group_items'.
    Returns:
        Tuple (total_items, total_spent).
    """
    total_items = items.count()
    total_spent = None
    if view == 'my_items':
        total_spent = items.aggregate(total=Sum('amount'))[
            'total'] or Decimal('0.00')
    elif view == 'group_items':
        total_spent = items.aggregate(total=Sum('actual_price'))[
            'total'] or Decimal('0.00')
    return total_items, total_spent


def paginate_items(request, items, page, page_size, group_id):
    """
    Paginates the queryset and generates pagination metadata.
    Args:
        request: The HTTP request object.
        items: Queryset of ReceiptItemSplit or ReceiptItem objects.
        page: The current page number.
        page_size: The number of items per page.
        group_id: The ID of the group.
    Returns:
        Tuple (paginated_items, pagination_metadata).
    """
    paginator = Paginator(items, page_size)
    page_obj = paginator.get_page(page)

    next_url = None
    previous_url = None
    if page_obj.has_next():
        next_params = request.query_params.copy()
        next_params['page'] = page_obj.next_page_number()
        next_url = reverse('history', kwargs={
                           'group_id': group_id}) + '?' + next_params.urlencode()
    if page_obj.has_previous():
        prev_params = request.query_params.copy()
        prev_params['page'] = page_obj.previous_page_number()
        previous_url = reverse(
            'history', kwargs={'group_id': group_id}) + '?' + prev_params.urlencode()

    pagination_metadata = {
        "current_page": page_obj.number,
        "page_size": page_size,
        "total_pages": paginator.num_pages,
        "next": next_url,
        "previous": previous_url
    }
    return page_obj.object_list, pagination_metadata


def prepare_items_for_serialization(items, view, user_member):
    """
    Prepares items for serialization by creating pseudo ReceiptItemSplit objects for group_items view.
    Args:
        items: List of ReceiptItemSplit or ReceiptItem objects.
        view: 'my_items' or 'group_items'.
        user_member: The GroupMember object for the authenticated user.
    Returns:
        List of ReceiptItemSplit objects (real or pseudo).
    """
    if view == 'my_items':
        return items
    else:
        return [ReceiptItemSplit(receipt_item=item, group_member=user_member) for item in items]


def validate_date(year, month, day):
    try:
        year = int(year)
        month = int(month)
        day = int(day)
        # Validate year, month, and day by creating a datetime object
        datetime(year=year, month=month, day=day)
        return True, (year, month, day)
    except (ValueError, TypeError):
        return False, "Invalid date: year, month, and day must form a valid date."


def get_date_range_for_day(year, month, day):
    target_date = datetime(year=year, month=month, day=day)
    start_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = target_date.replace(
        hour=23, minute=59, second=59, microsecond=999999)
    return start_date, end_date