from decimal import Decimal
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .serializers import (
    UserSerializer, 
    GroupSerializer, 
    GroupMemberSerializer, 
    ShoppingListSerializer, 
    ShoppingListItemSerializer, 
    CategorySerializer, 
    ReceiptSerializer, 
    ReceiptItemSplitSerializer, 
    DebtSerializer,
    GroupMemberExpenseSerializer,
    DailyExpenseSerializer,
    MonthlyExpenseSerializer,
    CategoryExpenseSerializer,
    ExpenseDetailSerializer,
    HistoryItemSerializer,
    )
from .models import Group, GroupMember, ShoppingList, ShoppingListItem, Category, ReceiptItemSplit, Receipt, Debt
from django.utils import timezone
import base64
import google.generativeai as genai
from django.conf import settings
from datetime import datetime
from .prompt import RECEIPT_PROCESSING_PROMPT  # Import the prompt
from django.shortcuts import get_object_or_404
import json
import re
from .utils import (
    validate_receipt_data, 
    create_receipt, 
    create_receipt_item_and_splits,
    update_debts,
    validate_year_and_month,
    get_date_range_for_month,
    calculate_total_expense_for_member,
    calculate_seven_day_expenses,
    calculate_monthly_expenses,
    calculate_category_expenses,
    calculate_daily_expenses,
    calculate_group_expenses,
    validate_payment_amount,
    sort_debts,
    validate_history_params,
    fetch_base_items,
    apply_search_filter,
    apply_category_filter,
    apply_sorting,
    calculate_summary_stats,
    paginate_items,
    prepare_items_for_serialization,
    validate_date,
    get_date_range_for_day,
)
from django.db import transaction
from django.db.models import Sum
from calendar import monthrange
from rest_framework_simplejwt.tokens import RefreshToken


class SignupView(APIView):
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Generate tokens for the user
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)
            return Response({
                'access': access_token,
                'refresh': refresh_token,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GroupCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GroupSerializer(
            data=request.data, context={'request': request})
        if serializer.is_valid():
            group = serializer.save()
            # Add creator as a member with custom name and icon
            member_data = {'group': group, 'user': request.user}
            if 'member_name' in request.data:
                member_data['name'] = request.data['member_name']
            if 'member_icon' in request.data:
                member_data['icon'] = request.data['member_icon']
            GroupMember.objects.create(**member_data)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GroupJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        invite_code = request.data.get('invite_code')
        try:
            group = Group.objects.get(invite_code=invite_code)
        except Group.DoesNotExist:
            return Response({'error': 'Invalid invite code'}, status=status.HTTP_404_NOT_FOUND)

        if GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'Already a member'}, status=status.HTTP_400_BAD_REQUEST)

        # Use provided name and icon, or defaults
        member_data = {
            'group': group,
            'user': request.user,
            'icon': request.data.get('icon', '👤'),
            # Default to username
            'name': request.data.get('member_name', request.user.username)
        }
        GroupMember.objects.create(**member_data)

        # Serialize the group object to match GroupCreateView's response
        serializer = GroupSerializer(group, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UserGroupsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        memberships = GroupMember.objects.filter(user=request.user)
        groups = [membership.group for membership in memberships]
        serializer = GroupSerializer(groups, many=True)
        return Response(serializer.data)


class GroupMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        # Ensure the user is a member of the group
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        members = GroupMember.objects.filter(group=group)
        serializer = GroupMemberSerializer(members, many=True)
        return Response(serializer.data)


class GroupWithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group_id = request.data.get('group_id')
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        membership = GroupMember.objects.filter(
            group=group, user=request.user).first()
        if not membership:
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_400_BAD_REQUEST)

        # Prevent creator from leaving (optional logic)
        if group.creator == request.user:
            return Response({'error': 'Creator cannot withdraw from the group'}, status=status.HTTP_403_FORBIDDEN)

        membership.delete()
        return Response({'message': 'Successfully withdrawn from group'}, status=status.HTTP_200_OK)


class ShoppingListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group_id = request.data.get('group_id')
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['group'] = group.id
        # Set position as the current number of lists in the group
        data['position'] = ShoppingList.objects.filter(group=group).count()

        serializer = ShoppingListSerializer(data=data)

        if serializer.is_valid():
            shopping_list = serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ShoppingListReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        list_ids = request.data.get('list_ids', [])
        if not list_ids:
            return Response({'error': 'List IDs are required'}, status=status.HTTP_400_BAD_REQUEST)

        shopping_lists = ShoppingList.objects.filter(group=group)
        lists_dict = {str(list.id): list for list in shopping_lists}

        for list_id in list_ids:
            if list_id not in lists_dict:
                return Response({'error': f'Shopping list {list_id} not found'}, status=status.HTTP_400_BAD_REQUEST)

        for position, list_id in enumerate(list_ids):
            shopping_list = lists_dict[list_id]
            shopping_list.position = position
            shopping_list.save()

        return Response({'message': 'Shopping lists reordered successfully'})


class ShoppingListItemUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, item_id):
        try:
            item = ShoppingListItem.objects.get(id=item_id)
        except ShoppingListItem.DoesNotExist:
            return Response({'error': 'Shopping list item not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check if the user is a member of the group that owns the shopping list
        shopping_list = item.shopping_list
        group = shopping_list.group
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        # Update the item with the provided data
        name = request.data.get('name', item.name)
        quantity = request.data.get('quantity', item.quantity)
        memo = request.data.get('memo', item.memo)

        # Validate the data
        if not name:
            return Response({'error': 'Name is required'}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(quantity, int) or quantity < 1:
            return Response({'error': 'Quantity must be a positive integer'}, status=status.HTTP_400_BAD_REQUEST)

        # Update the item
        item.name = name
        item.quantity = quantity
        item.memo = memo if memo else None
        item.save()

        serializer = ShoppingListItemSerializer(item)
        return Response(serializer.data)


class ShoppingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        shopping_lists = ShoppingList.objects.filter(group=group)
        serializer = ShoppingListSerializer(shopping_lists, many=True)
        return Response(serializer.data)


class ShoppingListItemCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shopping_list_id = request.data.get('shopping_list_id')
        try:
            shopping_list = ShoppingList.objects.get(id=shopping_list_id)
        except ShoppingList.DoesNotExist:
            return Response({'error': 'Shopping list not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=shopping_list.group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['shopping_list'] = shopping_list.id
        # Calculate the position (number of existing items)
        data['position'] = shopping_list.items.count()

        serializer = ShoppingListItemSerializer(data=data)

        if serializer.is_valid():
            # Create the item with added_by set explicitly
            item = serializer.save(added_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ShoppingListItemReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, shopping_list_id):
        try:
            shopping_list = ShoppingList.objects.get(id=shopping_list_id)
        except ShoppingList.DoesNotExist:
            return Response({'error': 'Shopping list not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=shopping_list.group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        # Expect a list of item IDs in the desired order
        item_ids = request.data.get('item_ids', [])
        if not item_ids:
            return Response({'error': 'Item IDs are required'}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch all items in the shopping list
        items = ShoppingListItem.objects.filter(shopping_list=shopping_list)
        items_dict = {str(item.id): item for item in items}

        # Validate that all provided item IDs exist
        for item_id in item_ids:
            if item_id not in items_dict:
                return Response({'error': f'Item {item_id} not found'}, status=status.HTTP_400_BAD_REQUEST)

        # Update the position of each item based on the new order
        for position, item_id in enumerate(item_ids):
            item = items_dict[item_id]
            item.position = position
            item.save()

        return Response({'message': 'Items reordered successfully'})


class ShoppingListItemToggleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, item_id):
        try:
            item = ShoppingListItem.objects.get(id=item_id)
        except ShoppingListItem.DoesNotExist:
            return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=item.shopping_list.group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        item.is_purchased = not item.is_purchased
        if item.is_purchased:
            item.purchased_at = timezone.now()
        else:
            item.purchased_at = None
        item.save()
        serializer = ShoppingListItemSerializer(item)
        return Response(serializer.data)


class ShoppingListDelete(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, list_id):
        try:
            shopping_list = ShoppingList.objects.get(id=list_id)

            # Optional: Check if user has permission to delete
            if shopping_list.created_by != request.user:
                return Response(
                    {"error": "You didn’t create this list!"},
                    status=status.HTTP_403_FORBIDDEN
                )

            shopping_list.delete()  # 👈 This triggers CASCADE deletion
            return Response({'message': 'Successfully delete the shopping list'}, status=status.HTTP_200_OK)

        except ShoppingList.DoesNotExist:
            return Response({'error': 'The list is not found'}, status=status.HTTP_404_NOT_FOUND)


class ShoppingListItemDelete(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        try:
            item = ShoppingListItem.objects.get(id=item_id)
            if item.added_by != request.user:
                return Response(
                    {"error": "You didn’t create this item!"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            item.delete()
            return Response({'message': 'Successfully delete the shopping item from list'}, status=status.HTTP_200_OK)

        except ShoppingListItem.DoesNotExist:
            return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)


class CategoryListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        categories = Category.objects.filter(group=group)
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)


class CategoryCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group_id = request.data.get('group_id')
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['group'] = group.id
        serializer = CategorySerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CategoryUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, category_id):
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return Response({'error': 'Category not found'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMember.objects.filter(group=category.group, user=request.user).exists():
            return Response({'error': 'You are not a member of this group'}, status=status.HTTP_403_FORBIDDEN)

        if category.is_default:
            return Response({'error': 'Default categories cannot be updated'}, status=status.HTTP_403_FORBIDDEN)

        serializer = CategorySerializer(
            category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Configure the Gemini API with the key from settings
genai.configure(api_key=settings.GEMINI_API_KEY)


class ReceiptPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Check if an image file was uploaded
        if 'image' not in request.FILES:
            return Response({"error": "No image file provided."}, status=status.HTTP_400_BAD_REQUEST)

        # Read the image file and convert it to base64
        image_file = request.FILES['image']
        image_data = image_file.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        try:
            # Use Gemini API to process the image with the imported prompt
            model = genai.GenerativeModel('gemini-2.0-flash')
            image_part = {
                "mime_type": "image/jpeg",
                "data": image_base64
            }
            response = model.generate_content(
                [RECEIPT_PROCESSING_PROMPT, image_part])

            # Extract the text from the response
            if not response.candidates or not response.candidates[0].content.parts:
                return Response({"error": "No content returned from Gemini API."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            raw_text = response.candidates[0].content.parts[0].text

            # Remove the Markdown code block markers (```json\n and \n```)
            json_match = re.search(r'```json\n([\s\S]*?)\n```', raw_text)
            if not json_match:
                return Response({"error": "Could not extract JSON from Gemini API response."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            json_string = json_match.group(1)

            # Parse the JSON string into a Python dictionary
            receipt_data = json.loads(json_string)

            # Validate the JSON structure
            required_fields = ['name', 'total_amount', 'subtotal', 'tax_amount', 'tax_rate',
                               'discount_amount', 'discount_rate', 'purchase_date', 'items']
            for field in required_fields:
                if field not in receipt_data:
                    return Response({"error": f"Missing required field in JSON: {field}"}, status=status.HTTP_400_BAD_REQUEST)

            if not isinstance(receipt_data['items'], list):
                return Response({"error": "Items must be a list."}, status=status.HTTP_400_BAD_REQUEST)

            for item in receipt_data['items']:
                required_item_fields = [
                    'name', 'general_name', 'quantity', 'price', 'actual_price', 'category']
                for field in required_item_fields:
                    if field not in item:
                        return Response({"error": f"Missing required field in item: {field}"}, status=status.HTTP_400_BAD_REQUEST)

            return Response(receipt_data, status=status.HTTP_200_OK)


        except json.JSONDecodeError as e:
            return Response({"error": f"Failed to parse JSON from Gemini API response: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": f"Error processing image with Gemini API: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReceiptConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)


        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)
        
        # Get the receipt data from the request
        receipt_data = request.data

        # Validate the receipt data
        is_valid, error_message = validate_receipt_data(receipt_data)
        if not is_valid:
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Use a transaction to ensure data consistency
            with transaction.atomic():
                # Create the receipt
                receipt = create_receipt(group, receipt_data, request.user)

                # Get all group members for splitting
                group_members = GroupMember.objects.filter(group=group)

                # Process each item and create splits
                for item_data in receipt_data['items']:
                    create_receipt_item_and_splits(
                        receipt, item_data, group_members, group
                    )
                
                # Update debts based on the new splits
                splits = ReceiptItemSplit.objects.filter(receipt_item__receipt=receipt)
                update_debts(splits, group)

                # Serialize and return the created receipt
                serializer = ReceiptSerializer(receipt)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ... (previous imports and code remain the same)

class ReceiptSplitsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, receipt_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the receipt and verify it belongs to the group
        receipt = get_object_or_404(Receipt, id=receipt_id, group=group)

        # Get all splits for the receipt
        splits = ReceiptItemSplit.objects.filter(receipt_item__receipt=receipt)

        # Serialize the splits
        serializer = ReceiptItemSplitSerializer(splits, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GroupDebtsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get all debts for the group
        debts = Debt.objects.filter(group=group)

        # Serialize the debts
        serializer = DebtSerializer(debts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GroupMonthlyExpensesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, year, month):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        try:
            # Validate year and month
            year = int(year)
            month = int(month)
            if not (1 <= month <= 12):
                return Response({"error": "Month must be between 1 and 12."}, status=status.HTTP_400_BAD_REQUEST)
            if year < 1900 or year > 9999:
                return Response({"error": "Year must be between 1900 and 9999."}, status=status.HTTP_400_BAD_REQUEST)

            # Calculate the date range for the month
            start_date = datetime(year, month, 1).date()
            # Get the last day of the month
            last_day = monthrange(year, month)[1]
            end_date = datetime(year, month, last_day).date()

            # Get all group members
            group_members = GroupMember.objects.filter(group=group)

            # Calculate expenses for each member
            expenses = []
            for member in group_members:
                # Sum the amounts from ReceiptItemSplit for this member within the date range
                total_expense = ReceiptItemSplit.objects.filter(
                    group_member=member,
                    receipt_item__receipt__purchase_date__range=(
                        start_date, end_date)
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

                expenses.append({
                    "group_member": member,
                    "total_expense": total_expense
                })

            # Serialize the results
            serializer = GroupMemberExpenseSerializer(expenses, many=True)
            return Response({
                "group_id": str(group.id),
                "year": year,
                "month": month,
                "expenses": serializer.data
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({"error": "Invalid year or month format."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the user’s group member record
        user_member = get_object_or_404(GroupMember, group=group, user=request.user)

        # Validate year and month
        year = request.query_params.get('year', datetime.now().year)
        month = request.query_params.get('month', datetime.now().month)
        is_valid, result = validate_year_and_month(year, month)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month = result

        # Calculate the date range for the month
        start_date, end_date = get_date_range_for_month(year, month)

        # 1. My Total Expense in This Month
        my_total_expense = calculate_total_expense_for_member(user_member, start_date, end_date)

        # 2. Chart and Graph Block
        # 2.1 Seven-Day Expense
        today = datetime.now().date()
        seven_day_expenses = calculate_seven_day_expenses(user_member, today)

        # 2.2 Monthly Expense (last 12 months)
        monthly_expenses = calculate_monthly_expenses(user_member, today)

        # 2.3 Expense by Category in This Month
        category_expenses = calculate_category_expenses(
            user_member, group, start_date, end_date)

        # 3. Group Total Expense and Ranking
        group_total_expense, member_expenses = calculate_group_expenses(
            group, start_date, end_date)

        # 4. Money Transfer Relationships
        debts = Debt.objects.filter(group=group).exclude(amount=0)
        # debts = Debt.objects.filter(group=group)
        sorted_debts = sort_debts(debts, user_member)

        # Serialize the data
        seven_day_serializer = DailyExpenseSerializer(
            seven_day_expenses, many=True)
        monthly_serializer = MonthlyExpenseSerializer(
            monthly_expenses, many=True)
        category_serializer = CategoryExpenseSerializer(
            category_expenses, many=True)
        member_expense_serializer = GroupMemberExpenseSerializer(
            member_expenses, many=True)
        debt_serializer = DebtSerializer(sorted_debts, many=True)

        return Response({
            "group_id": str(group.id),
            "my_member_id": str(user_member.id),  # Added my_member_id
            "year": year,
            "month": month,
            "my_total_expense": my_total_expense,
            "charts": {
                "seven_day_expenses": seven_day_serializer.data,
                "monthly_expenses": monthly_serializer.data,
                "category_expenses": category_serializer.data
            },
            "group_expenses": {
                "total": group_total_expense,
                "members": member_expense_serializer.data
            },
            "debts": debt_serializer.data
        }, status=status.HTTP_200_OK)


class CalendarExpensesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, year, month):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the user’s group member record
        user_member = get_object_or_404(
            GroupMember, group=group, user=request.user)

        # Validate year and month
        is_valid, result = validate_year_and_month(year, month)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month = result

        # Calculate the date range for the month
        start_date, end_date = get_date_range_for_month(year, month)

        # Calculate daily expenses for the month
        daily_expenses = calculate_daily_expenses(
            user_member, start_date, end_date)

        # Serialize the data
        serializer = DailyExpenseSerializer(daily_expenses, many=True)
        return Response({
            "group_id": str(group.id),
            "year": year,
            "month": month,
            "daily_expenses": serializer.data
        }, status=status.HTTP_200_OK)


class OtherExpenseDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, member_id):
        # Get the group and verify it exists
        group = get_object_or_404(Group, id=group_id)

        # Verify the authenticated user is a member of the group
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the target group member record (based on member_id)
        target_member = get_object_or_404(
            GroupMember, id=member_id, group=group)

        # Validate year and month
        year = request.query_params.get('year', datetime.now().year)
        month = request.query_params.get('month', datetime.now().month)
        is_valid, result = validate_year_and_month(year, month)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month = result

        # Calculate the date range for the month
        start_date, end_date = get_date_range_for_month(year, month)

        # Get all splits for the target member in the date range
        splits = ReceiptItemSplit.objects.filter(
            group_member=target_member,
            receipt_item__receipt__purchase_date__range=(start_date, end_date)
        ).order_by('receipt_item__receipt__purchase_date')

        # Serialize the splits
        serializer = ExpenseDetailSerializer(splits, many=True)
        return Response({
            "group_id": str(group.id),
            "year": year,
            "month": month,
            "expenses": serializer.data
        }, status=status.HTTP_200_OK)


class MyExpenseDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the user’s group member record
        user_member = get_object_or_404(GroupMember, group=group, user=request.user)

        # Validate year and month
        year = request.query_params.get('year', datetime.now().year)
        month = request.query_params.get('month', datetime.now().month)
        is_valid, result = validate_year_and_month(year, month)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month = result

        # Calculate the date range for the month
        start_date, end_date = get_date_range_for_month(year, month)

        # Get all splits for the user in the date range
        splits = ReceiptItemSplit.objects.filter(
            group_member=user_member,
            receipt_item__receipt__purchase_date__range=(start_date, end_date)
        ).order_by('receipt_item__receipt__purchase_date')

        # Serialize the splits
        serializer = ExpenseDetailSerializer(splits, many=True)
        return Response({
            "group_id": str(group.id),
            "year": year,
            "month": month,
            "expenses": serializer.data
        }, status=status.HTTP_200_OK)


class MyExpenseDetailsByDateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        # Get the user’s group member record
        user_member = get_object_or_404(
            GroupMember, group=group, user=request.user)

        # Validate year, month, and date
        year = request.query_params.get('year', datetime.now().year)
        month = request.query_params.get('month', datetime.now().month)
        day = request.query_params.get('day', datetime.now().day)

        # Validate year and month first
        is_valid, result = validate_year_and_month(year, month)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month = result

        # Validate the full date
        is_valid, result = validate_date(year, month, day)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        year, month, day = result

        # Calculate the date range for the specific day
        start_date, end_date = get_date_range_for_day(year, month, day)

        # Get all splits for the user on the specific date
        splits = ReceiptItemSplit.objects.filter(
            group_member=user_member,
            receipt_item__receipt__purchase_date__range=(start_date, end_date)
        ).order_by('receipt_item__receipt__purchase_date')

        # Serialize the splits
        serializer = ExpenseDetailSerializer(splits, many=True)
        return Response({
            "group_id": str(group.id),
            "year": year,
            "month": month,
            "day": day,
            "expenses": serializer.data
        }, status=status.HTTP_200_OK)


class PayDebtView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id, debt_id):
        print("group_id", group_id)
        print("debt_id", debt_id)
        print("request", request.data.get('amount'))
        # Get the group and verify the user is a member
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)
        print("request2", request.data.get('amount'))
        # Get the debt and verify it belongs to the group
        debt = get_object_or_404(Debt, id=debt_id, group=group)
        print("request3", request.data.get('amount'))
        # Verify the user is either the debtor or creditor
        user_member = get_object_or_404(
            GroupMember, group=group, user=request.user)
        if user_member not in [debt.debtor, debt.creditor]:
            return Response({"error": "You are not involved in this debt."}, status=status.HTTP_403_FORBIDDEN)
        print("request4", request.data.get('amount'))
        # Validate the payment amount
        is_valid, result = validate_payment_amount(
            request.data.get('amount'), debt.amount)
        print("request5", result)
        print("is_valid", is_valid)
        if not is_valid:
            return Response({"error": result}, status=status.HTTP_400_BAD_REQUEST)
        payment_amount = result
        print("request6", request.data.get('amount'))
        try:
            with transaction.atomic():
                # Update the debt
                debt.amount -= payment_amount
                if debt.amount <= 0:
                    debt.delete()
                    return Response({"message": "Debt fully paid and deleted."}, status=status.HTTP_200_OK)
                else:
                    debt.save()
                    serializer = DebtSerializer(debt)
                    return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            print("e", e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        # Get the group and verify the user is a member
        print("get HistoryView")
        group = get_object_or_404(Group, id=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({"error": "You are not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

        print("get group")
        # Get the user’s group member record
        user_member = get_object_or_404(
            GroupMember, group=group, user=request.user)

        print("get user_member")
        # Validate query parameters
        is_valid, params = validate_history_params(request)
        if not is_valid:
            return Response({"error": params}, status=status.HTTP_400_BAD_REQUEST)

        print("get validate_history_params")
        # Fetch base items
        items = fetch_base_items(group, user_member, params['view'])

        print("get fetch_base_items")
        # Apply filters and sorting
        items = apply_search_filter(items, params['view'], params['search'])
        items = apply_category_filter(
            items, params['view'], params['category_id'])
        items = apply_sorting(
            items, params['view'], params['sort_by'], params['sort_order'])

        # Calculate summary stats
        total_items, total_spent = calculate_summary_stats(
            items, params['view'])

        # Paginate items
        paginated_items, pagination = paginate_items(
            request, items, params['page'], params['page_size'], group_id
        )

        # Prepare items for serialization
        serialized_items = prepare_items_for_serialization(
            paginated_items, params['view'], user_member)

        # Serialize the items
        serializer = HistoryItemSerializer(serialized_items, many=True)

        return Response({
            "group_id": str(group.id),
            "view": params['view'],
            "total_items": total_items,
            "total_spent": total_spent,
            "items": serializer.data,
            "pagination": pagination
        }, status=status.HTTP_200_OK)
