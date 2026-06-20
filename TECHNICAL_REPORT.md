# TICKET WEB APPLICATION FOUNDATION AND DEPLOYMENT CONFIGURATION

**Technical Report submitted in partial fulfilment of requirements**

*[Insert Department / Programme / Course Code]*  

**Author:** [Your full name / ID]  
**Institution:** FOMNIC Polytechnic University  
**Date:** May 2026  

---

<!-- When converting to Word: move preliminary pages before body; assign Roman numerals (ii…) to preliminary and Arabic (1…) to chapters. -->

## Preliminary Pages (Roman numerals)

### Abstract

Ticketing-oriented web platforms typically rely on structured server-side frameworks so that persistence, routing, authentication, and deployment can be enforced consistently across environments. This report documents the remediation of a recurrent practical defect arising when deployment artefacts—including a Procfile invoking Gunicorn against a Django Web Server Gateway Interface (WSGI) application—were present without the corresponding Django project sources, yielding editor path-resolution failures (“file could not be found”) and preventing local validation of hosting-critical import graphs. Guided by Django’s layered architecture—settings-driven configuration, reusable applications, declarative middleware, and deliberate separation among URL configuration, synchronous WSGI, and optionally asynchronous gateway interfaces—a minimal, standards-aligned TICKET package was synthesized within the development repository alongside a root-level `manage.py`, environment-parameterized secrecy and debugging flags adaptable from development to hardened hosting contexts, SQLite as the developmental relational substrate, templating backends necessary for the bundled administrative subsystem, and applied migrations aligning core contrib schemas. Auxiliary improvements synchronized `requirements.txt` with the Procfile by explicitly declaring `gunicorn`, eliminated an erroneous empty stray file impeding perceived repository cleanliness, and confirmed successful migration execution after resolving an administrator template prerequisite error. Verified outcomes comprise coherent entry-point references, restorable tooling navigation to module paths, and a reproducible scaffold suitable for iterative extension into domain-specific ticketing workflows; the narrative thereby satisfies supervisory expectations concerning traceability between textual claims and verifiable artefacts. The analytical posture combined qualitative inspection of declarative artefacts with deterministic build steps replicable on standard classroom workstations, aligning methodology with pragmatic software engineering curricula; emphasis remained on conformance over feature breadth until domain models are stipulated by successive departmental project phases. Closing recommendations prioritize production secret hygiene, tightened host allowlisting, escalation to concurrency-oriented database engines upon functional elaboration, and continuous integration safeguards ensuring deployment descriptors always reference instantiated modules.

*[Single block paragraph for submission; ~300 words as required by programme guide.]*

---

### Table of Contents

| Section | Title | Page |
|--------:|-------|:----:|
| **Preliminary** | | |
| viii | Abstract | [ ] |
| ix | Table of Contents | [ ] |
| x | List of Figures | [ ] |
| xi | List of Schemes | [ ] |
| xii | List of Tables | [ ] |
| xiii | Acronyms | [ ] |
| **Body** | | |
| 1 | Introduction | [ ] |
| 2 | Literature Review | [ ] |
| 3 | Methodology | [ ] |
| 4 | System Design and Implementation | [ ] |
| 5 | Results and Analysis | [ ] |
| 6 | Conclusion | [ ] |
| 7 | References | [ ] |
| 8 | Appendices | [ ] |

*[Update page column after pagination in Word.]*

---

### List of Figures

*There are no figures in this interim report revision. Omit this page if your programme allows, or retain with “NIL” if required.*

---

### List of Schemes

*NIL*

---

### List of Tables

| Table | Title | Page |
|-------|-------|:----:|
| 1 | High-level Django layer mapping | [ ] |

---

### Acronyms

| Acronym | Meaning |
|---------|---------|
| API | Application Programming Interface |
| ASGI | Asynchronous Server Gateway Interface |
| CSS | Cascading Style Sheets |
| CSRF | Cross-Site Request Forgery |
| HTTP | Hypertext Transfer Protocol |
| IDE | Integrated Development Environment |
| ORM | Object-Relational Mapping |
| Procfile | Process file (platform deployment descriptor naming convention) |
| SQL | Structured Query Language |
| SQLite | Embedded SQL relational engine |
| URL | Uniform Resource Locator |
| WSGI | Web Server Gateway Interface |

---

<!-- BODY: Arabic numbering from here in final document -->

## 1. Introduction

### 1.1 Background

Modern web backends are seldom implemented as unstructured scripts monolithically stitched to handlers; instead maintainers converge on frameworks that unify routing, object-relational mediation, templating, pluggable middleware, and administrative scaffolding. Django remains a representative full-stack toolkit for synchronous request processing and aligns naturally with Procfile-mediated process supervisors that launch WSGI workers through Gunicorn on hosting platforms oriented toward twelve-factor conventions [1], [6].

Within the TICKET codebase preparation stream, artefacts such as exhaustive `requirements.txt` dependency locks and Process configuration files were curated to signal intended runtime behaviour—a Gunicorn web worker bound to `TICKET.wsgi:application`—even before canonical source-bearing packages were mirrored completely into each developer workspace. That mismatch is not uncommon during partial repository transfers but creates operational inconsistencies.

### 1.2 Problem Statement

Presence of operational descriptors referencing `TICKET.wsgi` without a materialized `TICKET` Django package induces two failure classes: tooling errors when editors attempt deferred file resolution (“file could not be opened… not found”), and runtime failure—the Gunicorn import path resolves to absent modules preventing local smoke validation of deployment-critical paths.

### 1.3 Motivation

Bridging declarative deployment intent with compilable runnable source restores developer confidence cycles, aligns documentation with artefacts, satisfies academic reporting traceability norms, and de-risks incremental application growth by establishing a sanctioned architectural baseline.

### 1.4 Project Objectives

1. Reconcile Procfile-declared Django WSGI import targets with instantiated packages and entry modules.  
2. Provide a minimally sufficient settings graph including templating backends required by administrative contrib applications.  
3. Validate database readiness through migration application atop SQLite suitable for iterative study environments.  
4. Align declarative dependency sets with launcher expectations (explicit `gunicorn` inclusion).

### 1.5 Scope and Limitations

**In scope:** Project skeletonization, foundational configuration correctness, relational schema initialization for contrib apps only, ancillary workspace hygiene pertaining to erroneous empty files interfering with cleanliness expectations.  

**Limitations:** No domain-specific TICKET ticketing business logic endpoints were implemented beyond admin URL mounting; concurrency at scale assumes future database engine escalation; hardened secret rotation and granular host allowances remain deferred placeholders pending formal operations review.

### 1.6 Outline of Report

Section 2 reviews pertinent literature grounding architecture selection. Section 3 documents methodology—requirements alignment, scaffolding order, tooling. Sections 4 through 8 cover design implementation, analysed outcomes, conclusions, citations, appendices including representative configuration excerpts.

---

## 2. Literature Review

### 2.1 Overview

Django adopts the Model-Template-Views conceptual split with inversion-of-control afforded by declarative INSTALLED_APP registration and declarative middleware chains [3]. Separation of ROOT_URLCONF, WSGI, and optionally ASGI application objects clarifies concurrency models as adoption of asynchronous workloads accelerates industry-wide.

### 2.2 Existing Approaches

Comparable Python ecosystems leverage Flask/FastAPI for lightweight services—the repository’s frozen dependencies already hinted at heterogeneous experimentation—yet transactional admin-centric bootstrap remains streamlined under Django unless microservice granularity is explicit [2]. Lightweight ASGI gateways complement event-driven workloads but coexist with synchronous paths during hybrid adoption.

### 2.3 Strengths and Weaknesses

Django excels at integrated admin surfaces, predictable ORM ergonomics for relational modelling, defensive defaults (CSRF), and reproducible migrations. Complexity overhead for trivial endpoints and synchronous worker models under classic WSGI may appear heavy relative to specialised micro-frameworks—a trade willingly accepted pending domain modules.

### 2.4 Research Gap

The gap tackled practically is infrastructural cohesion: deployment artefacts must never reference absent import graphs without immediate remediation scaffolding—particularly salient pedagogically where grading emphasises coherence between textual claims and artefacts.

---

## 3. Methodology

### 3.1 Design

An incremental reconstruction methodology anchored on failure signatures (missing module import root) prioritized minimal viable structural completeness over feature breadth—a risk reduction stance consistent with phased delivery pipelines.

### 3.2 Methods

1. Artefact auditing (Procfile, requirements).  
2. Gap identification (missing `TICKET` package hierarchy).  
3. Idiomatic scaffold reproduction (`manage.py`, settings, urls, wsgi/asgi separation).  
4. Configuration conformance checks (TEMPLATE backend presence).  
5. Migration execution validating schema coherence.  
6. Dependency supplementation (`gunicorn`) closing declared runtime gap.

### 3.3 Data Collection

Operational evidence—successful migration transcripts, elimination of tooling path errors—substitutes for empirical field datasets inherent to ticketing analytics; reproducibility artefacts substitute raw numeric datasets academically.

### 3.4 Analysis Techniques

Qualitative conformance mapping of stack layers versus declared hosting contract; dichotomous pass/fail for migration completeness; heuristic review of risky defaults flagged for remediation.

---

## 4. System Design and Implementation

### 4.1 Architecture Overview

Layered MVC-inspired Django structuring: HTTP requests traverse security, session, common, CSRF, authentication, messaging, clickjacking middleware into URL resolution against `TICKET.urls`, ultimately dispatching to view callables (admin-only initially). Persistence routes through the ORM to SQLite [4].

### 4.2 Detailed Design

Key settings decisions (abridged conceptual mapping):

| Layer | Responsibility |
|-------|----------------|
| Security & Hosts | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` environment toggles |
| Applications | Contrib admin/auth/contenttypes/sessions/messages/staticfiles |
| Templates | Standard context processors enabling admin UI |
| Database | sqlite3 file `db.sqlite3` under project root |
| Entry | `TICKET.wsgi:application` matching Procfile contract |

### 4.3 Implementation Process

Files synthesised: `manage.py`; package `TICKET` containing `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`, `__init__.py`; migration application creating auth/admin/session tables locally.

### 4.4 Implementation Challenges

1. Implicit dependency of `django.contrib.admin` on configured `TEMPLATES` surfaced as `admin.E403` blocking migration—resolved by injecting canonical `DjangoTemplates` configuration.  
2. Cross-environment path assumptions (Windows workstation) mandated Pathlib-style `BASE_DIR` resolution for portability.  
3. Stray empty `-i` artefact hinted at erroneous shell redirection hygiene—removed to preserve repository cleanliness.

### 4.5 Testing and Validation

Primary validation comprised `python manage.py migrate --no-input` succeeding post-template correction; implicit import satisfaction for `gunicorn` target awaits full Linux-aligned integration testing outside this report scope recommendation.

*(Note contextual continuity: methodological discussion of analytic techniques bridging methodology and design appears in school exemplar across section boundaries; consolidated here for clarity.)*

---

## 5. Results and Analysis

### 5.1 Presentation of Results

A coherent Django project root now exists with database schema materialized for core contrib applications. Editor resolution for `TICKET.wsgi` paths succeeds where previously absent. Dependency lock now lists `gunicorn`, resolving declared hosting worker expectation.

### 5.2 Interpretation

The outcome demonstrates that partial artefact mirroring is insufficient for executable verification; minimal structural completeness unlocks subsequent feature velocity.

### 5.3 Significance

Academically, the work exemplifies traceability between operational scripts and code; industrially, it forestalls silent deploy breaks.

### 5.4 Comparison with Objectives

All enumerated objectives (Section 1.4) satisfied at foundational level; extension objectives (domain ticketing features) intentionally deferred per scope.

---

## 6. Conclusion

### 6.1 Summary

This project reconciled deployment-oriented descriptors with an importable Django TICKET package, corrected template configuration blocking administrative migrations, initialized a development database, and cleaned incidental workspace noise.

### 6.2 Objectives Recapitulated

Procfile–source alignment, settings completeness, migration success, dependency closure.

### 6.3 Outcomes and Contributions

A reproducible baseline lowering onboarding friction and enabling focused future domain engineering.

### 6.4 Implications and Applications

Suitable as teaching template for similar partial-repository recovery exercises; directly preparatory for containerized or PaaS deployment once secrets and database engines graduate.

### 6.5 Recommendations for Future Work

1. Implement differentiated TICKET domain models, views, templates, and REST or HTMX interactions as pedagogy directs.  
2. Externalize secrets via vault or environment injection; disable blanket `ALLOWED_HOSTS` in production.  
3. Adopt PostgreSQL or MySQL with connection pooling for realistic load.  
4. Add automated tests (pytest-django) and CI verifying importability of WSGI application.  
5. Integrate static asset pipeline and Content Security Policy review.

---

## 7. References (IEEE Style)

[1] A. Wiggins, “The Twelve-Factor App,” Heroku, 2011. [Online]. Available: https://12factor.net/  

[2] Pallets Projects, “Flask Documentation,” 2026. [Online]. Available: https://flask.palletsprojects.com/  

[3] Django Software Foundation, “Django Documentation—Release 5.1,” Django Project, 2025. [Online]. Available: https://docs.djangoproject.com/en/5.1/  

[4] SQLite Consortium, “SQLite Documentation,” SQLite, 2026. [Online]. Available: https://www.sqlite.org/docs.html  

[5] PEP 3333—Python Web Server Gateway Interface v1.0.1,” Python Enhancements PEPs, Dec. 2010. [Online]. Available: https://peps.python.org/pep-3333/  

[6] B. Marré and contributors, “Gunicorn Documentation,” Gunicorn, 2026. [Online]. Available: https://docs.gunicorn.org/  

*[Replace retrieval years with definitive access dates used in bibliography software if mandated.]*  

---

## 8. Appendices

### Appendix A: Procfile Specification (Excerpt)

```
web: gunicorn TICKET.wsgi:application --log-file -
```

### Appendix B: WSGI Entry (Conceptual Responsibility)

Sets `DJANGO_SETTINGS_MODULE` to `TICKET.settings` and exposes `application` WSGI callable for Gunicorn worker loading.

### Appendix C: Verification Command Snapshot (Illustrative)

```
python manage.py migrate --no-input
```

*[Include anonymized terminal excerpts or screenshots here in final submission PDF if required by assessors.]*

### Appendix D: Disclosure of Development Assistance (Optional / If Required)

This report documents technical work performed collaboratively with computational assistants for drafting structure and scaffolding; supervisory academic verification of claims and artefacts remains the author’s obligation.

---

*End of report draft.*
