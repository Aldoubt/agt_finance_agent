# Local test workflow

## Windows test workspace

Create a local test folder next to the navigation development workspace:

```
finance_test_workspace/

├── input/
│   └── raw purchase files
│
├── output/
│   └── generated archive
│
└── agt_finance_agent/
    └── source checkout
```

## Test command (planned)

```
python -m agt_finance_agent.cli --input ./input --output ./output
```

Benchmark data should be added without modifying the original files.
