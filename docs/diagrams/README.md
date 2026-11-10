# OpsPilot AWS architecture diagram

- [PNG image](opspilot-aws-architecture.png): 3600 × 2800 pixels for sharing and slides.
- [Standalone SVG](opspilot-aws-architecture.svg): vector artwork with embedded AWS icons.
- [Vector PDF](opspilot-aws-architecture.pdf): export for printing or presentations.
- [Python source](../../scripts/build_architecture_diagram.py): layout, connections and labels.

The diagram uses the reference's dark background, square AWS service icons, numbered
blue markers and AWS Cloud boundary. It describes the architecture defined in
[template.yaml](../../template.yaml), not a currently running environment. The demo's
AWS resources were removed on November 10, 2026.

The main runtime path is browser → HTTP API → API Lambda → SQS → worker Lambda →
Bedrock. DynamoDB holds workflow state, receipts, sessions and audit records. IAM roles,
CloudWatch logs/alarm and SQS delivery redrive appear as supporting connections. The
lower lane separates deployment artifacts and cost alerts from request traffic.
S3 stores SAM deployment packages; dashboard assets are served by the API Lambda.
The budget email endpoint does not represent a separately deployed SES resource.

## Rebuild

Generate the SVG with Python 3.13 and the standard library:

```powershell
.venv/Scripts/python.exe scripts/build_architecture_diagram.py
```

For PNG/PDF export, install `requirements-ui.txt` and use the existing local Chrome:

```powershell
.venv/Scripts/python.exe scripts/build_architecture_diagram.py --render
```

These commands are local only. They do not provision resources or call AWS APIs.

## Icon attribution

Service icons in `assets/aws/` are original AWS Architecture Icons from the July 31,
2026 package linked on the [official AWS architecture icons page](https://aws.amazon.com/architecture/icons/).
The standalone SVG embeds them without changing their artwork. AWS permits these assets
to be used in architecture diagrams; AWS names and service marks belong to Amazon.
The browser and email endpoint symbols are drawn in the Python source.

Package source:
`https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip`.
