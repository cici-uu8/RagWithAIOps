INSERT INTO sync_jobs (job_id, source_system, target_system, status, last_sync_at, updated_rows)
VALUES
  ('job-meta-001', 'crm', 'metadata-store', 'running', '2026-06-02 09:50:00', 1200),
  ('job-meta-002', 'erp', 'metadata-store', 'success', '2026-06-02 09:40:00', 840)
ON DUPLICATE KEY UPDATE status = VALUES(status), updated_rows = VALUES(updated_rows);

INSERT INTO sync_runs (run_id, job_id, started_at, finished_at, status, latency_ms)
VALUES
  ('run-001', 'job-meta-001', '2026-06-02 09:55:00', NULL, 'running', 3400),
  ('run-002', 'job-meta-002', '2026-06-02 09:35:00', '2026-06-02 09:36:00', 'success', 620)
ON DUPLICATE KEY UPDATE status = VALUES(status), latency_ms = VALUES(latency_ms);

INSERT INTO orders (order_id, customer_id, status, total_amount, created_at)
VALUES
  ('order-1001', 'cust-001', 'paid', 199.90, '2026-06-02 09:20:00'),
  ('order-1002', 'cust-002', 'pending', 59.00, '2026-06-02 09:45:00')
ON DUPLICATE KEY UPDATE status = VALUES(status), total_amount = VALUES(total_amount);

INSERT INTO order_items (item_id, order_id, sku, quantity, unit_price)
VALUES
  ('item-1001-1', 'order-1001', 'sku-iphone-case', 2, 49.95),
  ('item-1001-2', 'order-1001', 'sku-usb-cable', 1, 99.90),
  ('item-1002-1', 'order-1002', 'sku-usb-cable', 1, 59.00)
ON DUPLICATE KEY UPDATE quantity = VALUES(quantity), unit_price = VALUES(unit_price);

INSERT INTO inventory_items (sku, warehouse_id, available_quantity, reserved_quantity, updated_at)
VALUES
  ('sku-iphone-case', 'wh-east', 120, 5, '2026-06-02 09:55:00'),
  ('sku-usb-cable', 'wh-east', 18, 12, '2026-06-02 09:55:00')
ON DUPLICATE KEY UPDATE available_quantity = VALUES(available_quantity), reserved_quantity = VALUES(reserved_quantity);

INSERT INTO inventory_reservations (reservation_id, sku, order_id, quantity, status, created_at)
VALUES
  ('res-1001', 'sku-iphone-case', 'order-1001', 2, 'confirmed', '2026-06-02 09:21:00'),
  ('res-1002', 'sku-usb-cable', 'order-1002', 1, 'pending', '2026-06-02 09:46:00')
ON DUPLICATE KEY UPDATE status = VALUES(status), quantity = VALUES(quantity);
