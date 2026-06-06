"""Vision Inspection System — pharma inline print & code verification.

Package layout (see docs/04-system-architecture.md):
  common/  shared types, geometry, event bus
  tools/   InspectionTool plugin interface + implementations (classic & AI)
  engine/  acquisition, dispatcher, worker pool, aggregator, pipeline
  domain/  data-model entities (Recipe/Region/...)
  models/  locked, versioned model registry (D-007)
"""

__version__ = "0.0.1"
