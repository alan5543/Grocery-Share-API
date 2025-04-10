from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Group, GroupMember, ShoppingListItem, ShoppingList, Category, ReceiptItemSplit, ReceiptItem, Receipt, Debt


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class GroupSerializer(serializers.ModelSerializer):
    creator = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Group
        fields = ['id', 'name', 'icon', 'creator', 'invite_code', 'created_at']

    def create(self, validated_data):
        validated_data['creator'] = self.context['request'].user
        return super().create(validated_data)


class GroupMemberSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all())

    class Meta:
        model = GroupMember
        fields = ['id', 'group', 'user', 'name', 'icon', 'joined_at']


class ShoppingListItemSerializer(serializers.ModelSerializer):
    # added_by = serializers.PrimaryKeyRelatedField(read_only=True)
    added_by = UserSerializer(read_only=True)  # 👈 Now shows full user details

    class Meta:
        model = ShoppingListItem
        fields = ['id', 'shopping_list', 'name', 'quantity',
                  'is_purchased', 'added_by', 'added_at', 'purchased_at', 'memo', 'position']


class ShoppingListSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    items = ShoppingListItemSerializer(many=True, read_only=True)

    class Meta:
        model = ShoppingList
        fields = ['id', 'group', 'name', 'created_by',
                  'created_at', 'updated_at', 'items', 'position']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'group', 'name', 'is_default', 'created_at']


class ReceiptItemSplitSerializer(serializers.ModelSerializer):
    group_member = GroupMemberSerializer(read_only=True)
    group_member_id = serializers.PrimaryKeyRelatedField(
        queryset=GroupMember.objects.all(), source='group_member', write_only=True
    )
    paid_by = GroupMemberSerializer(read_only=True)
    paid_by_id = serializers.PrimaryKeyRelatedField(
        queryset=GroupMember.objects.all(), source='paid_by', write_only=True
    )

    class Meta:
        model = ReceiptItemSplit
        fields = ['id', 'receipt_item', 'group_member', 'group_member_id',
                  'amount', 'paid_by', 'paid_by_id', 'created_at']


class ReceiptItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True, required=False
    )
    splits = ReceiptItemSplitSerializer(many=True, read_only=True)

    class Meta:
        model = ReceiptItem
        fields = ['id', 'receipt', 'category', 'category_id', 'name', 'general_name', 'quantity', 'price',
                  'actual_price', 'added_at', 'splits']


class ReceiptSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.PrimaryKeyRelatedField(read_only=True)
    items = ReceiptItemSerializer(many=True, read_only=True)

    class Meta:
        model = Receipt
        fields = ['id', 'group', 'name', 'total_amount', 'subtotal', 'tax_amount', 'tax_rate',
                  'discount_amount', 'discount_rate', 'purchase_date', 'uploaded_by', 'error',
                  'created_at', 'updated_at', 'items']


class DebtSerializer(serializers.ModelSerializer):
    debtor = GroupMemberSerializer(read_only=True)
    creditor = GroupMemberSerializer(read_only=True)
    related_to_me = serializers.SerializerMethodField()

    class Meta:
        model = Debt
        fields = ['id', 'group', 'debtor', 'creditor',
                  'amount', 'last_updated', 'related_to_me']

    def get_related_to_me(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user_member = GroupMember.objects.filter(
            group=obj.group, user=request.user).first()
        if not user_member:
            return False
        return user_member in [obj.debtor, obj.creditor]



class GroupMemberExpenseSerializer(serializers.Serializer):
    group_member = GroupMemberSerializer()
    total_expense = serializers.DecimalField(max_digits=10, decimal_places=2)


class DailyExpenseSerializer(serializers.Serializer):
    date = serializers.DateField()
    total_expense = serializers.DecimalField(max_digits=10, decimal_places=2)


class MonthlyExpenseSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    total_expense = serializers.DecimalField(max_digits=10, decimal_places=2)


class CategoryExpenseSerializer(serializers.Serializer):
    category = CategorySerializer()
    total_expense = serializers.DecimalField(max_digits=10, decimal_places=2)


class ExpenseDetailSerializer(serializers.ModelSerializer):
    receipt_item = ReceiptItemSerializer()
    receipt_name = serializers.CharField(source='receipt_item.receipt.name')
    purchase_date = serializers.DateField(
        source='receipt_item.receipt.purchase_date')

    class Meta:
        model = ReceiptItemSplit
        fields = ['id', 'receipt_item', 'amount',
                  'receipt_name', 'purchase_date']


class HistoryItemSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='receipt_item.name')
    general_name = serializers.CharField(source='receipt_item.general_name')
    price = serializers.DecimalField(
        source='receipt_item.price', max_digits=10, decimal_places=2)
    actual_price = serializers.DecimalField(
        source='receipt_item.actual_price', max_digits=10, decimal_places=2)
    quantity = serializers.FloatField(source='receipt_item.quantity')
    category = CategorySerializer(
        source='receipt_item.category', read_only=True)
    receipt_name = serializers.CharField(source='receipt_item.receipt.name')
    purchase_date = serializers.DateField(
        source='receipt_item.receipt.purchase_date')

    class Meta:
        model = ReceiptItemSplit
        fields = ['id', 'name', 'general_name', 'price', 'actual_price', 'quantity', 'category',
                  'receipt_name', 'purchase_date']
