"""Build OpsPilot's AWS service diagram as a standalone SVG and optional PNG/PDF.

Run: python scripts/build_architecture_diagram.py --render
Only local files and a headless browser are used; no AWS calls are made.
"""

import argparse
import copy
import html
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "diagrams"
ASSETS = OUTPUT / "assets" / "aws"
WIDTH, HEIGHT = 1800, 1400
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def esc(value):
    return html.escape(str(value), quote=True)


def text(x, y, value, size=20, color="#e9edf4", anchor="middle", weight=400, extra=""):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}" font-weight="{weight}" {extra}>{esc(value)}</text>'
    )


def label(x, y, value, size=17, color="#a8b6ca", anchor="middle"):
    return text(
        x,
        y,
        value,
        size,
        color,
        anchor,
        extra='paint-order="stroke" stroke="#080b10" stroke-width="8" stroke-linejoin="round"',
    )


def edge(path, kind="runtime", both=False):
    colors = {"runtime": "#c3cedb", "ops": "#9ba9bd", "deploy": "#6eabf1", "retry": "#f6b65b"}
    dash = 'stroke-dasharray="7 7"' if kind in {"ops", "deploy", "retry"} else ""
    start = f'marker-start="url(#{kind}Start)"' if both else ""
    return (
        f'<path d="{path}" fill="none" stroke="{colors[kind]}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round" {dash} '
        f'{start} marker-end="url(#{kind}End)"/>'
    )


def badge(cx, cy, number):
    return f'<circle cx="{cx}" cy="{cy}" r="19" fill="#0073d8" stroke="#204a72" stroke-width="1.4"/>' + text(
        cx, cy + 6, number, 18, "#ffffff", weight=700
    )


def service(icon, cx, cy, title, subtitle, detail=None, number=None, size=100):
    x, y = cx - size / 2, cy - size / 2
    parts = [f'<use href="#icon-{icon}" x="{x}" y="{y}" width="{size}" height="{size}"/>']
    if number is not None:
        parts.append(badge(x + size + 5, y + 1, number))
    parts += [
        text(cx, y + size + 31, title, 21, weight=650),
        text(cx, y + size + 56, subtitle, 17, "#b7c3d5"),
    ]
    if detail:
        parts.append(text(cx, y + size + 79, detail, 15, "#8393aa"))
    return "\n".join(parts)


def laptop(cx, cy, title, subtitle, number=None):
    x, y = cx - 53, cy - 39
    parts = [
        f'<rect x="{x}" y="{y}" width="106" height="74" rx="8" fill="#a5aab1"/>',
        f'<rect x="{x + 7}" y="{y + 7}" width="92" height="56" rx="3" fill="#f1f3f5"/>',
        f'<path d="M{x - 9} {y + 81} H{x + 115} L{x + 106} {y + 94} H{x} Z" fill="#b9bec4"/>',
        f'<path d="M{cx - 18} {y + 81} H{cx + 18} L{cx + 14} {y + 85} H{cx - 14} Z" fill="#7e8793"/>',
        text(cx, cy + 89, title, 18, weight=650),
        text(cx, cy + 113, subtitle, 16, "#a8b6ca"),
    ]
    if number:
        parts.append(badge(cx + 61, cy - 43, number))
    return "\n".join(parts)


def symbols():
    result = []
    for path in sorted(ASSETS.glob("*.svg")):
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        symbol = ET.Element(f"{{{NS}}}symbol", {"id": "icon-" + path.stem, "viewBox": root.attrib["viewBox"]})
        # Every official icon uses generic IDs. Prefix them so symbols cannot collide.
        ids = {
            node.attrib["id"]: f"{path.stem}-{i}" for i, node in enumerate(root.iter()) if "id" in node.attrib
        }
        for child in root:
            node = copy.deepcopy(child)
            for descendant in node.iter():
                for key, value in list(descendant.attrib.items()):
                    if key == "id":
                        descendant.attrib[key] = ids[value]
                    else:
                        for old, new in ids.items():
                            value = value.replace(f"url(#{old})", f"url(#{new})")
                            if value == "#" + old:
                                value = "#" + new
                        descendant.attrib[key] = value
            symbol.append(node)
        result.append(ET.tostring(symbol, encoding="unicode"))
    for kind, color in {
        "runtime": "#c3cedb",
        "ops": "#9ba9bd",
        "deploy": "#6eabf1",
        "retry": "#f6b65b",
    }.items():
        for suffix, orientation in [("End", "auto"), ("Start", "auto-start-reverse")]:
            result.append(
                f'<marker id="{kind}{suffix}" viewBox="0 0 10 10" refX="8" refY="5" '
                f'markerWidth="7" markerHeight="7" orient="{orientation}">'
                f'<path d="M1 1 L8 5 L1 9" fill="none" stroke="{color}" stroke-width="1.6"/></marker>'
            )
    return "\n".join(result)


def build_svg():
    parts = [
        f'<svg xmlns="{NS}" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        'role="img" aria-labelledby="diagram-title diagram-description">',
        '<title id="diagram-title">OpsPilot AWS architecture</title>',
        '<desc id="diagram-description">Browser dashboard connects through API Gateway to an API Lambda. '
        "The API stores demo sessions and workflow state in DynamoDB and queues workflow IDs in SQS. "
        "SQS invokes a worker Lambda, which calls Bedrock Nova Micro and saves checkpoints and simulation receipts. "
        "Both functions use IAM roles and CloudWatch logging. Failed SQS deliveries go to a dead-letter queue "
        "monitored by a CloudWatch alarm. SAM and CloudFormation deploy resources using S3 code artifacts. "
        "AWS Budgets sends an email cost alert. This documents the retired demonstration deployment.</desc>",
        "<defs>",
        symbols(),
        "</defs>",
        '<rect width="1800" height="1400" fill="#080b10"/>',
        '<g font-family="Segoe UI,Arial,Helvetica,sans-serif">',
        text(50, 64, "OpsPilot", 36, "#ffffff", "start", 750),
        text(230, 64, "AWS architecture", 29, "#c4d0e1", "start", 450),
        text(
            50,
            99,
            "Evidence-led offboarding  /  human approval  /  simulated access changes",
            18,
            "#8d9eb6",
            "start",
        ),
        '<rect x="1462" y="36" width="282" height="42" rx="6" fill="#101a28" stroke="#263a52"/>',
        text(1603, 63, "SERVERLESS  /  us-east-1", 16, "#acd3ff", weight=600),
        '<rect x="240" y="140" width="1500" height="1170" fill="none" stroke="#3c4b61" stroke-width="1.5"/>',
        '<rect x="254" y="125" width="215" height="30" fill="#080b10"/>',
        text(266, 148, "aws", 24, "#f5f7fa", "start", 700),
        text(326, 148, "AWS Cloud", 21, "#d6e0ed", "start", 600),
        text(1705, 175, "RUNTIME", 13, "#6f849e", "end", 600, 'letter-spacing="2"'),
        # Core HTTP and asynchronous request path.
        edge("M165 450 H350", both=True),
        edge("M450 450 H630", both=True),
        edge("M730 450 H930"),
        edge("M1030 450 H1210"),
        edge("M1310 450 H1550", both=True),
        # State and session persistence (the same DynamoDB table).
        edge("M680 400 V255 H960", both=True),
        edge("M1260 400 V255 H1060", both=True),
        # DLQ redrive after delivery retries, distinct from caught workflow failures.
        edge("M1030 478 H1120 V790 H1030", "retry"),
        # Separate IAM execution roles; dashed paths denote permissions, not calls.
        edge("M400 740 V660 H560 V480 H630", "ops"),
        edge("M450 790 H510 V688 H1109 Q1120 672 1131 688 H1185 V480 H1210", "ops"),
        # Logs from API and worker. Curved bridges distinguish crossing edges.
        edge("M730 478 H820 V640 H1109 Q1120 624 1131 640 H1174 Q1185 624 1196 640 H1430 V740", "ops"),
        edge("M1310 478 H1430 V740", "ops"),
        edge("M1030 817 H1380", "ops"),
        # Deployment is intentionally separated from request traffic.
        '<path d="M270 1040 H1710" stroke="#2c3b50" stroke-width="1.3"/>',
        text(270, 1075, "DEPLOYMENT", 13, "#7595bb", "start", 700, 'letter-spacing="2"'),
        edge("M165 1170 H380", "deploy"),
        edge("M100 1128 V1102 H760 V1133", "deploy"),
        edge("M710 1170 H480", "deploy"),
        edge("M430 1120 V1000", "deploy"),
        edge("M1160 1170 H1450", "ops"),
        # Edge captions are placed after lines, before service symbols.
        label(254, 422, "HTTPS"),
        label(540, 422, "HTTP routes"),
        label(830, 422, "Workflow ID"),
        label(1120, 422, "SQS trigger"),
        label(1430, 422, "Converse API"),
        label(820, 227, "Sessions + workflow state", 16),
        label(1160, 227, "Checkpoints + receipts", 16),
        label(1142, 737, "After 4 receives", 15, "#f6b65b", "start"),
        label(625, 715, "Scoped execution roles", 15),
        label(910, 622, "API logs", 15),
        label(1450, 615, "Worker logs", 15, anchor="start"),
        label(1200, 845, "Queue-depth alarm", 15),
        label(270, 1143, "sam deploy", 16, "#8abaff"),
        label(560, 1090, "Upload code packages", 15, "#8abaff"),
        label(595, 1144, "Package references", 16, "#8abaff"),
        label(455, 1025, "Provisions resources above", 15, "#8abaff", "start"),
        label(1310, 1143, "50% of $2 / month", 16),
        laptop(100, 450, "Requester / approver", "Browser dashboard", 1),
        service("api-gateway", 400, 450, "Amazon API Gateway", "HTTP API", number=2),
        service("lambda", 680, 450, "AWS Lambda", "API function", "Sessions, commands, dashboard assets", 3),
        service("dynamodb", 1010, 255, "Amazon DynamoDB", "Workflows, sessions and audit", number=4),
        service("sqs", 980, 450, "Amazon SQS", "Workflow queue", "Messages contain only workflow IDs", 5),
        service(
            "lambda", 1260, 450, "AWS Lambda", "Worker function", "Policy, tools and approved execution", 6
        ),
        service(
            "bedrock", 1600, 450, "Amazon Bedrock", "Nova Micro", "Tool proposals + receipt summaries", 7
        ),
        service(
            "iam",
            400,
            790,
            "AWS IAM",
            "Separate API and worker roles",
            "Permissions enforced independently",
            size=100,
        ),
        service("sqs", 980, 790, "Amazon SQS", "Dead-letter queue", "Exhausted delivery retries", 8),
        service(
            "cloudwatch", 1430, 790, "Amazon CloudWatch", "Logs + dead-letter alarm", "7-day log retention", 9
        ),
        # A short application-level control note, rather than invented service nodes.
        '<rect x="650" y="945" width="1040" height="48" rx="5" fill="#0d1520" stroke="#26384d"/>',
        text(
            1170,
            975,
            "Human approval binds to the exact action. Execution creates a simulation receipt.",
            17,
            "#a9bdd5",
        ),
        laptop(100, 1170, "Developer", "AWS SAM CLI"),
        service("cloudformation", 430, 1170, "AWS CloudFormation", "SAM application stack", size=100),
        service("s3", 760, 1170, "Amazon S3", "Deployment artifacts only", size=100),
        service("budgets", 1110, 1170, "AWS Budgets", "Account-wide cost alert", size=100),
        # Email is an endpoint, not a separately provisioned SES service.
        '<rect x="1454" y="1137" width="92" height="66" rx="5" fill="#172435" stroke="#90a6c0" stroke-width="2"/>',
        '<path d="M1458 1142 L1500 1175 L1542 1142 M1458 1198 L1484 1173 M1542 1198 L1516 1173" '
        'fill="none" stroke="#bdcce0" stroke-width="2.4"/>',
        text(1500, 1251, "Email notification", 21, weight=650),
        text(1500, 1276, "Budget threshold alert", 17, "#b7c3d5"),
        # Legend and historical scope.
        '<path d="M260 1343 H308" stroke="#c3cedb" stroke-width="2.2"/>',
        text(320, 1349, "Runtime flow", 14, "#a4b4c9", "start"),
        '<path d="M475 1343 H523" stroke="#9ba9bd" stroke-width="2.2" stroke-dasharray="7 7"/>',
        text(535, 1349, "Permissions / observability", 14, "#a4b4c9", "start"),
        '<path d="M792 1343 H840" stroke="#6eabf1" stroke-width="2.2" stroke-dasharray="7 7"/>',
        text(852, 1349, "Deployment only", 14, "#a4b4c9", "start"),
        text(1725, 1349, "IAM and Budgets are account-level controls.", 14, "#8393aa", "end"),
        text(
            260,
            1381,
            "Reproducible demo architecture from template.yaml. AWS resources retired November 10, 2026.",
            14,
            "#73869f",
            "start",
        ),
        "</g></svg>",
    ]
    return "\n".join(parts)


def render(svg, png, pdf):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2)
        page.set_content(
            "<html><head><style>html,body{margin:0;background:#080b10}</style></head><body>"
            + svg
            + "</body></html>"
        )
        page.evaluate("document.fonts.ready")
        page.locator("svg").first.screenshot(path=str(png))
        page.pdf(
            path=str(pdf),
            width=f"{WIDTH}px",
            height=f"{HEIGHT}px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--render", action="store_true", help="Also export a 2x PNG and a vector PDF using Playwright/Chrome"
    )
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    ET.fromstring(svg)  # Validate the complete standalone XML before writing.
    target = OUTPUT / "opspilot-aws-architecture.svg"
    target.write_text(svg, encoding="utf-8")
    print(target.relative_to(ROOT))
    if args.render:
        render(svg, target.with_suffix(".png"), target.with_suffix(".pdf"))
        print(target.with_suffix(".png").relative_to(ROOT))
        print(target.with_suffix(".pdf").relative_to(ROOT))


if __name__ == "__main__":
    main()
