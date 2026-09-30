from pathlib import Path

from shop.csv_import import import_orders_csv
from shop.models import Customer, Product
from shop.repository import CustomerRepository, OrderRepository, ProductRepository


def _repos():
    products = ProductRepository()
    products.add(Product(sku="widget", name="Widget", unit_price_cents=500))
    customers = CustomerRepository()
    customers.add(Customer(customer_id="c1", name="Ada"))
    return products, customers, OrderRepository()


def test_all_valid(tmp_path: Path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,customer_id,sku,quantity\no1,c1,widget,2\no1,c1,widget,1\n")
    products, customers, orders = _repos()
    report = import_orders_csv(csv_path, products, customers, orders)
    assert report.imported_order_ids == ["o1"]
    assert report.errors == []
    assert orders.get("o1").subtotal_cents == 1500


def test_bad_sku_rejects_whole_order(tmp_path: Path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,customer_id,sku,quantity\no1,c1,unknown,1\n")
    products, customers, orders = _repos()
    report = import_orders_csv(csv_path, products, customers, orders)
    assert report.imported_order_ids == []
    assert len(report.errors) == 1
    assert "o1" not in [o.order_id for o in orders.all()]


def test_non_numeric_quantity(tmp_path: Path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,customer_id,sku,quantity\no1,c1,widget,abc\n")
    products, customers, orders = _repos()
    report = import_orders_csv(csv_path, products, customers, orders)
    assert report.imported_order_ids == []
    assert len(report.errors) == 1


def test_duplicate_order_id_rejected(tmp_path: Path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,customer_id,sku,quantity\no1,c1,widget,1\n")
    products, customers, orders = _repos()
    import_orders_csv(csv_path, products, customers, orders)
    report = import_orders_csv(csv_path, products, customers, orders)
    assert report.imported_order_ids == []
    assert len(report.errors) == 1
