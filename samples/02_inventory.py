class InventoryTracker:
    def __init__(self, warehouse_code):
        self.warehouse_code = warehouse_code
        self.stock_levels = {}

    def update_stock(self, item_sku, quantity):
        current_qty = self.stock_levels.get(item_sku, 0)
        new_qty = current_qty + quantity
        self.stock_levels[item_sku] = new_qty
        return new_qty

    def check_availability(self, item_sku, threshold=10):
        qty = self.stock_levels.get(item_sku, 0)
        return qty >= threshold
