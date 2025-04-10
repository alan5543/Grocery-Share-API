from django.db import models
from django.contrib.auth.models import User
import uuid


class Group(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)  # Supports emojis via UTF-8
    # Emoji icon, default to house
    icon = models.CharField(max_length=10, blank=True, default='🏠')
    creator = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='created_groups')
    invite_code = models.CharField(max_length=50, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self._state.adding  # Check if this is a new group
        if not self.invite_code:
            # Simple 8-char invite code
            self.invite_code = str(uuid.uuid4())[:8]
        super().save(*args, **kwargs)

        if is_new:  # Create default categories for new groups
            default_categories = [
                "Food Groceries",
                "Household Product",
                "Dining and Takeout",
                "Personal Entertainment",
                "Miscellaneous",
                "Others",
            ]

            for category_name in default_categories:
                Category.objects.create(
                    group=self, name=category_name, is_default=True)

    def __str__(self):
        return self.name


class GroupMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='group_memberships')
    # Emoji icon, default to person
    icon = models.CharField(max_length=10, blank=True, default='👤')
    # Custom name in group, defaults to username if blank
    name = models.CharField(max_length=255, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group', 'user')  # Prevent duplicate memberships

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.user.username  # Default to username if no custom name provided
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} in {self.group.name}"


class ShoppingList(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='shopping_lists')
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='created_shopping_lists')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    position = models.IntegerField(default=0)  # Add position field

    class Meta:
        # Sort by position, then creation time
        ordering = ['position', 'created_at']

    def __str__(self):
        return f"{self.name} (Group: {self.group.name})"


class ShoppingListItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shopping_list = models.ForeignKey(
        ShoppingList, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    is_purchased = models.BooleanField(default=False)
    added_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='added_items')
    added_at = models.DateTimeField(auto_now_add=True)
    purchased_at = models.DateTimeField(null=True, blank=True)
    memo = models.CharField(max_length=255, null=True,
                            blank=True)  # New memo field
    position = models.IntegerField(default=0)  # Add position field

    class Meta:
        # Sort by position, then creation time
        ordering = ['position', 'added_at']

    def __str__(self):
        return f"{self.name} (Qty: {self.quantity}, Purchased: {self.is_purchased})"


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)  # To mark default categories
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Prevent duplicate category names in a group
        unique_together = ('group', 'name')

    def __str__(self):
        return f"{self.name} (Group: {self.group.name})"


class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='receipts')
    name = models.CharField(max_length=255)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_rate = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    # Indexed for time-based queries
    purchase_date = models.DateField(null=True, blank=True, db_index=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_receipts')
    error = models.CharField(max_length=255, null=True, blank=True)
    # Indexed for time-based queries
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (Group: {self.group.name})"


class ReceiptItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='items')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='receipt_items', db_index=True)  # Indexed for category-based queries
    name = models.CharField(max_length=255)
    general_name = models.CharField(max_length=255, blank=True)
    quantity = models.FloatField(default=1.0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    actual_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (Qty: {self.quantity}, Price: {self.price})"


class ReceiptItemSplit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt_item = models.ForeignKey(ReceiptItem, on_delete=models.CASCADE, related_name='splits')
    group_member = models.ForeignKey(GroupMember, on_delete=models.CASCADE, related_name='receipt_item_splits', db_index=True)  # Indexed for user-based queries
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Amount this member owes
    paid_by = models.ForeignKey(GroupMember, on_delete=models.CASCADE, related_name='receipt_item_payments', null=True, blank=True)  # Who paid for this split
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('receipt_item', 'group_member')

    def __str__(self):
        return f"{self.group_member.name} owes {self.amount} for {self.receipt_item.name}"


class Debt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='debts')
    debtor = models.ForeignKey(GroupMember, on_delete=models.CASCADE, related_name='debts_owed', db_index=True)  # Indexed for debtor-based queries
    creditor = models.ForeignKey(GroupMember, on_delete=models.CASCADE, related_name='debts_due', db_index=True)  # Indexed for creditor-based queries
    # Net amount debtor owes creditor
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('group', 'debtor', 'creditor')

    def __str__(self):
        return f"{self.debtor.name} owes {self.creditor.name} {self.amount} in {self.group.name}"
