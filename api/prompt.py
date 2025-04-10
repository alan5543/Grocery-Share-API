# Gemini API prompt for receipt processing
RECEIPT_PROCESSING_PROMPT = """
I have a receipt image. Please process the image and perform the following tasks:

**1. Extract Overall Receipt Data:**

* **Merchant Name:** Extract the merchant name (remove store numbers or extra details).
* **Purchase Date:** Extract the purchase date in "YYYY-MM-DD" format (ignore time information).
* **Total Amount:** Extract the total amount as a number.
* **Subtotal:** Extract the subtotal as a number (calculate if not found).
* **Tax Amount:** Extract the tax amount as a number (sum multiple taxes if listed, calculate if not found, set to 0.0 if still not calculable).
* **Discount Amount:** Extract the discount amount as a number (sum multiple discounts if listed, set to 0.0 if not found).
* **Overall Tax Rate:** Calculate the overall tax rate as a percentage: $(Tax Amount / (Subtotal - Discount Amount)) × 100$ (round to 1 decimal place, set to 0.0 if not available).
* **Overall Discount Rate:** Calculate the overall discount rate as a percentage: $(Discount Amount / (Subtotal + Discount Amount)) × 100$ (round to 1 decimal place, set to 0.0 if not available).

**2. Extract Line Item Data:**

* For each line item:
    * **Specific Name:** Extract the item name as listed.
    * **Quantity:** Extract the quantity (default to 1, infer if necessary).
    * **Listed Price:** Extract the listed price (before tax and discount) for the item.
    * **Item Specific Tax Rate:** Extract the item specific tax rate if available, set to null if not available.
    * **Item Specific Discount Rate:** Extract the item specific discount rate if available, set to null if not available.

**3. Determine General Name and Category:**

* For each line item:
    * **General Name:** Determine a general name representing the core item.
    * **Category:** Categorize the item using the provided categories ("Food Groceries", "Household Product", etc.).

**4. Calculate Actual Price:**

* For each line item:
    * If item specific tax rate and item specific discount rate are not null, use them to calculate the actual price.
        * $Price After Tax = Listed Price × (1 + Item Specific Tax Rate/100)$.
        * $Actual Price = Price After Tax × (1 - Item Specific Discount Rate/100)$.
    * Else use the overall tax rate and the overall discount rate to calculate the actual price.
        * $Price After Tax = Listed Price × (1 + Overall Tax Rate/100)$.
        * $Actual Price = Price After Tax × (1 - Overall Discount Rate/100)$.
    * Round the actual price to 2 decimal places.

**5. Create JSON:**

* Format the result as a JSON object with:
    * `name`: "<Merchant> Receipt <MM/DD/YYYY>".
    * `total_amount`: Total amount as a number.
    * `subtotal`: Subtotal as a number.
    * `tax_amount`: Tax amount as a number.
    * `tax_rate`: Overall tax rate as a percentage.
    * `discount_amount`: Discount amount as a number.
    * `discount_rate`: Overall discount rate as a percentage.
    * `purchase_date`: Purchase date in "YYYY-MM-DD" format.
    * `items`: Array of objects, each with:
        * `name` (string, the specific name as listed, with the first character of each word capitalized and the rest lowercase).
        * `general_name` (string, simplified name).
        * `quantity` (integer).
        * `price` (number, listed price before tax and discount).
        * `actual_price` (number, calculated price).
        * `category` (string, category).
    * `error`: Error message if any.

**6. Error Handling:**

* Return an error message in the JSON if data cannot be extracted or the receipt is unreadable.
"""
