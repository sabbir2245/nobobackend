# Project Nabanno: Software Development Requirements Checklist

## 1. Post Management & Product Details
### Time Availability
- [ ] **Expiration Logic:** Add a numerical data type option for "Time Availability" when a farmer creates a post. 
- [ ] **Auto-Delete:** Implement logic to automatically delete the post once the specified time frame expires.

### Product Quantity Type
- [ ] **Unit Selection:** Add an option in the post creation section to list products either **per KG** or **per piece**.

## 2. Bidding & Negotiation System
- [ ] **Initial Bid:** Allow the customer to place 1 initial bid, which triggers a notification to the farmer.
- [ ] **Counter Bid (Farmer):** The farmer can respond with 1 final/last price.
  - *UI Requirement:* Place this counter-bid option under a question box with phrasing like: *"কত হলে বেচবেন?"* (How much will you sell it for?).
- [ ] **Customer Confirmation:** The customer receives a notification for the counter bid with options to **"Confirm"** or **"Reject"**.
- [ ] **Order Confirmation:** If the customer confirms, prompt them to complete the advance payment to finalize the order.

## 3. Payment Integrations & Flows
### Advance Payment Flow (Initial 50%)
- [ ] **Checkout Interface:** Customer proceeds to checkout and is prompted to pay 50% of the total order amount.
- [ ] **Payment Methods UI:** Display a bKash number and QR code.
  - *Future-Proofing:* Keep UI placeholders for merchant bKash account QR and BanglaQR (to easily enable these once the merchant bank account is acquired).
- [ ] **Transaction Verification (Custom UddoktaPay Logic):** 
  - Allow the customer to manually send money or scan the QR, then input the Transaction ID (TrxID) into the app.
  - Implement a backend cross-check: verify the customer's inputted TrxID against the TrxID extracted from incoming SMS notifications to automatically confirm the payment.
- [ ] **Admin Dashboard Logging:** Automatically generate/update a spreadsheet in the Admin Portal tracking the advance dues owed to the farmers.

### Final Payment Flow (Remaining 50%)
- [ ] **Shipment Stage UI:** During the shipment stage, display a button on the customer's dashboard stating: **"Complete your payment to receive the order"**.
- [ ] **Payment Method:** Customer pays the remaining 50% balance using the exact same custom TrxID verification method as the advance payment.
- [ ] **Handover Authorization:** Once the final payment is confirmed via the Admin Panel, automatically send a confirmation message to the delivery person authorizing the product handover.
- [ ] **Farmer Due Settlement (Remaining 50%):** 
  - *Current Phase:* Generate a list of remaining farmer dues with checkboxes so administrative staff can manually tick them off after sending the bKash funds.
  - *Future Automation:* Build the architecture to automate this process via Bizzpay (either by uploading the spreadsheet or via their API) once the merchant bank account is ready.

## 4. Delivery System
- [ ] **Batch Assignment:** Delivery personnel should see available delivery batches filtered/sorted by location proximity.
- [ ] **Pickup Confirmation:** 
  - Once a delivery person accepts a batch and loads the truck, they must click a **"Product Picked"** button.
  - *Customer UI:* This action updates the customer's app status to show the product is in the **"Shipping"** stage.
- [ ] **Delivery & Handover:** 
  - Upon reaching the customer, the customer completes the final 50% payment (as outlined in the Payment Flows).
  - Delivery person receives a real-time notification instructing them to hand over the product.
- [ ] **Shipment Completion:** After the physical handover, the delivery person clicks a **"Shipment Completed"** button to close out the order lifecycle.

## 5. User Profiles
### Customer Reviews
- [ ] **Review Storage:** Store and display customer reviews permanently on the respective farmer's profile. Ensure any attached pictures remain intact and formatted properly.
