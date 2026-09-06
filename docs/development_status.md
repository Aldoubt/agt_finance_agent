# Development Status

## Current milestone: v0.1 core pipeline

Completed:

- Repository architecture
- Document scanner skeleton
- Document classifier interface
- Invoice parser interface
- Finance entity models
- SQLite persistence foundation

Next:

1. Implement PDF text extraction
2. Implement invoice field extraction rules
3. Add benchmark runner for 2026_04 test case
4. Implement order/payment/image relationship matching
5. Generate DOCX and Excel archives

The project keeps the core algorithm independent from GUI/API layers.
