# V0.2 implementation notes

## Source of truth

`core/workbench/batch.py` owns a persisted batch and managed copies of its inputs. Asset, invoice and item identities are stable UUIDs. Filenames are display/source metadata, not relation keys. Exact-byte duplicate files are deduplicated by SHA-256. A batch can start with photographs alone.

Automatic parsing creates editable invoice facts and proposed relations. Human confirmation is stored separately. Incremental import or suggestion refresh does not replace confirmed decisions. State is saved by temporary-file replacement.

## UI

`agt_finance_agent/workbench_gui.py` is the default Tkinter desktop entry: welcome/recent batches and four guided steps. File analysis, PDF/image loading, export validation and generation run in worker threads; Tk changes are marshalled to the UI thread. The V0.1 photo review remains available through `--legacy-review`; `--analysis-only` retains its original contract.

## Export contract

`core/generators/export_plan.py` freezes confirmed batch facts into one `ExportPlan`. It does not parse inputs again. The plan governs invoice order, product order, final PDF names, Word captions and Excel rows. The Excel contract remains exactly eight columns, worksheet `采购统计`, sequential product rows and a total row.

Amounts are decimal values with cent precision. Each invoice is reconciled individually. Confirmed product pictures/order proofs/payment proofs are counted independently; packaging pictures are not product photos. Optional missing evidence is reported, while unreadable/changed inputs, duplicate invoices and inconsistent monetary facts prevent a successful final export.

Output is built in a temporary sibling directory and verified before publication. Existing amount directories are never appended to. A user-authorized same-batch update uses staged replacement with rollback. Original PDF bytes are copied unchanged. State/cache/validation metadata stay outside the financial archive.

## Validation and release

- Unit/behavior regressions: `python -m pytest -q tests`.
- Real desktop smoke: `python tools/smoke_workbench_gui.py --workspace-root <temp> --screenshot-dir <temp>` (requires a display).
- Packaged application check: `AGTFinanceAgent.exe --self-test --check-ocr --workspace-root <temp>` writes `self_test_report.json` and exercises the actual bundled OCR/runtime plus an exported fictional batch.
- Windows build: `tools/build_windows_v0_2.ps1`; GitHub workflow `windows-preview.yml` builds a downloadable prerelease only after checks pass.

Synthetic tests establish implementation behavior, not acceptance of every real invoice layout or every Windows desktop. User trial remains required for actual procurement material and ergonomics.
