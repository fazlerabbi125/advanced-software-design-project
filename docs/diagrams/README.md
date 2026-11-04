# Report diagrams

Sources and rendered images for the diagrams in the CS6451 report. They match the
final code on `main` (4 November 2026).

| File | Report figure | Source format | What it shows |
|---|---|---|---|
| `00-use-cases.drawio` (pages UCD1, UCD2, UCD3) | 4.1, 4.2, 4.3 | draw.io | Use-case diagrams: Booking & Waitlist, Biometric Check-in, Operations & Admin |
| `01-architecture` | 5.1 | Mermaid | Architecture overview: routers, services, entities and the Docker services |
| `07-package-diagram` | 5.2 | SVG only (hand laid out) | High-level package diagram from the code's imports |
| `02a-class-domain` | 6.1 | Mermaid | Domain classes |
| `02b-class-access-membership` | 6.2 | Mermaid | Strategy, State and Factory Method, with pre- and post-conditions |
| `02c-class-booking` | 6.3 | Mermaid | Builder, Chain of Responsibility, scheduled jobs and the Observer |
| `03-sequence-book-session` | 6.4 | Mermaid | Book Session sequence |
| `04-sequence-check-in` | 6.5 | Mermaid | Check In by Biometric Scan at a VIP room |
| `08-state-chart` | 6.6 | PlantUML | Membership state chart |
| `05-er-diagram` | 6.7 | Mermaid | Implemented database schema |
| `06-version-control-commits` | 8.1 | PNG only | Pull requests merged into dev per member |
| `09-design-package` | 10.1 | PlantUML | Design-time package diagram |
| `10-component` | 10.2 | PlantUML | Component diagram |
| `11-deployment` | 10.3 | PlantUML | Deployment diagram |

## Rendering

PlantUML (the UML workbench used for section 10, version 1.2026.9):

```bash
plantuml -tpng -Sdpi=200 docs/diagrams/09-design-package.puml
```

draw.io: open `00-use-cases.drawio` at https://app.diagrams.net (File > Open from > Device) and export each page as PNG or SVG.

Mermaid: paste the `.mmd` file into https://mermaid.live, or render it with the
Mermaid CLI:

```bash
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/01-architecture.mmd -o docs/diagrams/01-architecture.svg
```

Dashed grey boxes marked «planned» are in the design but not in the code yet.
