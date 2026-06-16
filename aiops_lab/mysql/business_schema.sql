CREATE TABLE IF NOT EXISTS sync_jobs (
  job_id VARCHAR(64) PRIMARY KEY,
  source_system VARCHAR(64) NOT NULL,
  target_system VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  last_sync_at DATETIME NOT NULL,
  updated_rows INT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
  run_id VARCHAR(64) PRIMARY KEY,
  job_id VARCHAR(64) NOT NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status VARCHAR(32) NOT NULL,
  latency_ms INT NOT NULL,
  INDEX idx_sync_runs_job_id (job_id),
  CONSTRAINT fk_sync_runs_job FOREIGN KEY (job_id) REFERENCES sync_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR(64) PRIMARY KEY,
  customer_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  total_amount DECIMAL(12, 2) NOT NULL,
  created_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  item_id VARCHAR(64) PRIMARY KEY,
  order_id VARCHAR(64) NOT NULL,
  sku VARCHAR(64) NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(12, 2) NOT NULL,
  INDEX idx_order_items_order_id (order_id),
  CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS inventory_items (
  sku VARCHAR(64) NOT NULL,
  warehouse_id VARCHAR(64) NOT NULL,
  available_quantity INT NOT NULL,
  reserved_quantity INT NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (sku, warehouse_id)
);

CREATE TABLE IF NOT EXISTS inventory_reservations (
  reservation_id VARCHAR(64) PRIMARY KEY,
  sku VARCHAR(64) NOT NULL,
  order_id VARCHAR(64) NOT NULL,
  quantity INT NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at DATETIME NOT NULL
);
