# EADE - eFoncier Adaptive Detection Engine

**An extensible, knowledge-driven and adaptive detection engine.**

EADE is an open-source project designed to build intelligent detection systems that improve progressively through configurable rules, accumulated knowledge, similarity analysis, and human feedback.

The project initially focuses on geospatial object detection for cadastral and land management applications, with a long-term vision of evolving toward a fully integrated machine learning engine.

> **Learn from corrections. Improve detection. Build intelligence progressively.**

## Project Status

🚧 **Early Development - Architecture & MVP**

EADE is currently in its initial development phase. The architecture and capabilities described below represent the project roadmap and may evolve.

The first implementation will focus on rule-based geospatial detection and human-assisted improvement.

## Vision

Traditional object detection systems rely heavily on predefined algorithms or pretrained AI models.

EADE explores a complementary approach: building an intelligent and explainable detection engine whose knowledge can be stored, analyzed, refined, and reused.

Instead of requiring a neural network from the beginning, EADE starts with:

- Configurable detection rules
- Feature extraction
- Knowledge-based classification
- Similarity matching
- Human corrections and validation
- Adaptive rule optimization
- Versioned knowledge and decision history

As the project evolves, these capabilities will provide the foundation for future machine learning integration.

## Key Features

### 1. Extensible Detection Engine

A modular detection architecture designed to support different detection providers and application domains.

Planned capabilities:

- Rule-based detection
- Feature-driven classification
- Context-aware decisions
- Configurable detection pipelines
- Multiple detection providers
- Explainable detection results

### 2. Adaptive Knowledge Base

EADE will maintain a structured knowledge base containing:

- Detection rules and conditions
- Object signatures and characteristics
- Validated detection examples
- Positive and negative examples
- Historical predictions
- Human corrections
- Rule performance metrics
- Versioned configurations

The knowledge base is designed to support improvements without requiring a neural network retraining process.

### 3. Human-in-the-Loop Learning

Human feedback is a core part of EADE's architecture.

The intended workflow:

1. EADE analyzes input data.
2. The engine proposes object detections.
3. A user reviews the results.
4. Incorrect detections are corrected.
5. Corrections are validated and stored.
6. The knowledge base is enriched.
7. Improved rules are evaluated.
8. Approved improvements are deployed.

Corrections do not automatically change production rules. Candidate improvements must pass validation before activation.

### 4. Geospatial Detection - EADE Geo

The first specialized extension of EADE focuses on geospatial analysis.

Targeted use cases include:

- Building footprint detection
- Rooftop identification
- Courtyard and paved-surface classification
- Road and access detection
- Wall and fence identification
- Vegetation classification
- Geospatial feature extraction
- Orthophoto analysis
- GIS vector data processing
- Cadastral parcel analysis
- Detection change monitoring

Supported input formats are planned to include GeoTIFF, GeoJSON, Shapefile, and other formats supported by the selected geospatial libraries.

### 5. Explainable Decision Engine

EADE aims to provide transparent detection results.

Each result may include:

- Detected object type
- Geometry or spatial location
- Extracted features
- Applied rules
- Similar reference objects
- Computed confidence or decision score
- Knowledge-base version
- Detection provider
- Validation status

Scores produced by the rule engine should not be interpreted as calibrated statistical probabilities unless explicitly validated.

### 6. Optional Integration

EADE is designed to remain optional in host applications.

Applications can enable or disable the engine without losing their existing processing capabilities.

Configuration options will include:

- Enable or disable EADE
- Enable or disable adaptive learning
- Control rule updates
- Select an active knowledge version
- Configure application-specific detection profiles
- Enable individual detection providers

## Architecture

EADE follows a modular architecture.

```text
EADE
│
├── eade-core
│   ├── Detection Engine
│   ├── Feature Engine
│   ├── Decision Engine
│   └── Provider Registry
│
├── eade-knowledge
│   ├── Knowledge Base
│   ├── Rules
│   ├── Object Signatures
│   └── Similarity Matching
│
├── eade-adaptation
│   ├── Feedback Analysis
│   ├── Rule Optimization
│   └── Knowledge Versioning
│
├── eade-feedback
│   ├── Human Corrections
│   ├── Review Workflow
│   └── Validation History
│
├── eade-geo
│   ├── Raster Processing
│   ├── Vector Processing
│   ├── Object Segmentation
│   └── Spatial Feature Extraction
│
├── eade-api
│   └── REST API
│
└── eade-ml
    └── Future Machine Learning Integration
```

The initial architecture is designed to use Java and Spring Boot, with PostgreSQL as the knowledge store and PostGIS for geospatial operations.

## Technology Stack

| Component | Planned Technology |
|---|---|
| Core engine | Java 17+ |
| Framework | Spring Boot |
| Database | PostgreSQL |
| Geospatial database | PostGIS |
| Image processing | OpenCV |
| Raster processing | GDAL |
| Geometry operations | JTS / GeoTools |
| API | REST / JSON |
| Frontend integration | Framework-independent |
| Future AI | Python / PyTorch / ONNX |

The architecture is intended to remain modular so that application-specific dependencies do not become mandatory for the core engine.

## Detection Pipeline

```text
Input Data
    |
    v
Feature Extraction
    |
    v
Candidate Detection
    |
    v
Knowledge Base Matching
    |
    v
Rule Evaluation
    |
    v
Decision & Scoring
    |
    v
Detection Results
    |
    v
Human Review
    |
    v
Validated Feedback
    |
    v
Knowledge Adaptation
```

The actual processing pipeline will depend on the selected detection provider.

## Roadmap

### EADE 1.0 - Knowledge-Driven Detection

- [ ] Implement modular core architecture
- [ ] Create the detection provider interface
- [ ] Develop configurable detection rules
- [ ] Implement knowledge storage
- [ ] Implement feature extraction
- [ ] Build basic similarity matching
- [ ] Integrate human feedback
- [ ] Add knowledge versioning
- [ ] Create EADE Geo MVP
- [ ] Publish REST API documentation
- [ ] Add automated tests

### EADE 2.0 - Adaptive Learning

- [ ] Analyze correction patterns
- [ ] Introduce statistical rule optimization
- [ ] Implement adaptive similarity scoring
- [ ] Add geographical detection profiles
- [ ] Implement rule performance evaluation
- [ ] Add automatic improvement proposals
- [ ] Introduce regression testing for rule updates
- [ ] Develop a knowledge supervision dashboard

### EADE 3.0 - Machine Learning

- [ ] Introduce machine learning providers
- [ ] Support custom-trained detection models
- [ ] Convert validated corrections into training datasets
- [ ] Implement model version management
- [ ] Integrate neural-network segmentation
- [ ] Combine rule-based and ML-based detection
- [ ] Support advanced geospatial classification

## First Use Case: eFoncier Africa

EADE's first integration target is **eFoncier Africa**, a cadastral and geospatial management platform.

The engine is intended to assist with analyzing orthophotos and cadastral parcels, identifying buildings, distinguishing constructed areas from courtyards, and supporting mass cadastral assessment workflows.

EADE provides detection and analysis support. Regulatory valuation calculations and official cadastral validation remain the responsibility of the host application and authorized professionals.

Although developed initially for eFoncier Africa, EADE is designed to support other applications and domains in the future.

## Repository Structure

The following structure is proposed for the initial implementation:

```text
eade/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── docs/
├── examples/
├── assets/
│   └── logo/
├── eade-core/
├── eade-knowledge/
├── eade-adaptation/
├── eade-feedback/
├── eade-geo/
├── eade-api/
└── tests/
```

This structure is a target architecture and does not imply that these modules are already implemented.

## Getting Started

Installation instructions, required configuration, sample datasets, and API examples will be added when the first runnable version is available.

The initial development work will focus on the core detection contracts, knowledge-base schema, rule execution, and the first geospatial detection workflow.

## Contributing

Contributions, technical discussions, testing, documentation improvements, and feature proposals are welcome.

Areas of interest include:

- Computer vision
- Geospatial processing
- Rule engines
- Knowledge-based systems
- Adaptive algorithms
- Machine learning
- Backend architecture
- Software testing
- Technical documentation

Contribution guidelines will be published in `CONTRIBUTING.md`.

## Principles

EADE is guided by the following principles:

**Modularity** - Detection providers and domain-specific features must remain independently extensible.

**Explainability** - Detection decisions should be traceable and understandable.

**Adaptability** - The engine should improve from verified knowledge and corrections.

**Reliability** - New rules must be tested before being deployed.

**Interoperability** - EADE should integrate with different applications through stable interfaces.

**Data Ownership** - Application owners retain control over their datasets and validated corrections.

**Future Readiness** - The architecture should support machine learning without requiring a complete redesign.

## License

The project is intended for public open-source development.

The final license will be selected and published before the first source-code release. Until then, the repository's public visibility alone does not grant permission to reuse or redistribute its code.

## Project Identity

**Name:** EADE

**Full Name:** eFoncier Adaptive Detection Engine

**Initial Domain:** Geospatial Detection and Cadastral Analysis

**Architecture:** Modular, Knowledge-Driven, Adaptive

**Long-Term Goal:** Intelligent and Machine Learning Detection Engine

---

**EADE - Learning from corrections. Evolving through knowledge.**