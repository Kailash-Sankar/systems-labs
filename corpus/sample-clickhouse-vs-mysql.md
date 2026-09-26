# ClickHouse vs MySQL

Sample corpus file for vector-search-lab. Replace `corpus/` with your own markdown, or set `CORPUS_PATH`.

## Column-oriented vs row-oriented storage

**ClickHouse** is a column-oriented database optimized for analytics. It stores data by column, which makes aggregations over large datasets fast — typical for OLAP workloads, merge tree engines, and time-series metrics.

**MySQL** is row-oriented: each row's columns are stored together on disk. That layout suits OLTP — many small reads and writes per row — but wide analytical scans touch more data than a column store.

## When to pick which

| | ClickHouse | MySQL |
|---|------------|-------|
| Workload | Analytics, dashboards, logs | Transactions, CRUD apps |
| Storage layout | Column store | Row store |
| Typical query | `SELECT sum(x) GROUP BY day` | `SELECT * FROM users WHERE id = ?` |

## MergeTree (ClickHouse)

ClickHouse's MergeTree family is the default table engine for large fact tables. Parts merge in the background; queries read only the columns they need.
