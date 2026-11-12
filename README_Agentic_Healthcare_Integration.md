# Agentic Healthcare Integration

## EXL × UCD Data & AI Hackathon 2026 --- Challenge 01

> **Challenge:** Build an AI-native, agentic integration fabric for a
> hybrid healthcare landscape.

This README is the project starting point for a team working on
**Challenge 01: Agentic Healthcare Integration**. It translates the
challenge brief into a practical build roadmap. Items explicitly stated
in the EXL--UCD brief are labelled **Hackathon brief**; suggested
implementation choices are labelled **Team proposal**.

------------------------------------------------------------------------

## 1. Problem statement

### Hackathon brief

A global healthcare client operates approximately **45 on-premise and
cloud systems**. Only around **25% expose usable APIs**, and even those
APIs need rework. Building integrations manually for the remaining
systems is slow, inconsistent and costly.

The team is asked to build a prototype that:

-   Integrates **3--5 mock systems**, for example a REST API, a legacy
    SQL database and an HL7 v2 or flat-file feed.
-   Uses AI agents to discover each system, choose an integration
    pattern and generate integration code.
-   Demonstrates the time and consistency gained compared with
    hand-built integrations.

The brief suggests **Synthea synthetic FHIR patient data**, the public
**HL7 FHIR specification**, and mock systems created by the team.
**Azure and .NET Core are preferred**, not mandatory.

**Important:** The challenge uses synthetic or mock data. Do not use
real patient data or personal health information.

## 2. Product vision

Build an **Agentic Healthcare Integration Factory**.

A user provides information about source and target systems. The
platform discovers their structures, proposes how they should
communicate, creates a mapping and integration artefacts, validates the
result, and presents the outcome for human review.

### Intended end-to-end workflow

1.  **Discover** --- inspect API specifications, database schemas,
    sample messages and files.
2.  **Design** --- identify field mappings and propose FHIR-aligned
    models and OpenAPI specifications.
3.  **Generate** --- create APIs, adapters, transformations and tests.
4.  **Validate** --- run contract, data-quality and security checks;
    report failures for correction.
5.  **Operate** --- expose integration status, logs, monitoring and
    alerts.

These five stages follow the suggested approach on page 6 of the
hackathon brief. Human review should remain at important decision and
release gates.

## 3. Scope for the prototype

### Required challenge scope

-   [ ] Select 3--5 mock healthcare systems.
-   [ ] Include more than one system/interface type.
-   [ ] Demonstrate at least one complete integration.
-   [ ] Use AI agents for system discovery, integration-pattern
    selection and code generation.
-   [ ] Show validation and evidence of time/consistency gains against a
    manual baseline.

### Suggested minimum viable prototype

Start with **three systems**, then add more only after the end-to-end
workflow works:

  -----------------------------------------------------------------------
  Mock system             Interface               Example information
  ----------------------- ----------------------- -----------------------
  Patient Management      REST API                Patient demographics

  Laboratory              SQL database            Laboratory observations

  Hospital Records        HL7 v2 message or flat  Encounter or clinical
                          file                    record data
  -----------------------------------------------------------------------

These are team-designed examples, not systems supplied by EXL. Use
synthetic records only.

### Out of scope for the initial prototype

-   Connecting to real hospitals or production healthcare systems.
-   Using real patient records.
-   Building a complete hospital-management product.
-   Automatically deploying generated integrations without review.
-   Claiming production-grade compliance or security from a hackathon
    prototype.

## 4. Proposed system architecture

The following is a **team proposal**, not a prescribed EXL architecture.

``` text
                         ┌─────────────────────────┐
                         │       Web UI            │
                         │ Add systems / Review /  │
                         │ Run / View results      │
                         └────────────┬────────────┘
                                      │
                         ┌────────────▼────────────┐
                         │  Workflow Orchestrator  │
                         │ state, approvals, runs  │
                         └────────────┬────────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
    ┌────────▼────────┐     ┌─────────▼────────┐     ┌─────────▼────────┐
    │ Discovery Agent │     │  Design Agent    │     │ Code Generation  │
    │ inspect systems │────▶│ mappings, FHIR,  │────▶│ Agent            │
    │ and schemas     │     │ integration plan │     │ APIs/adapters    │
    └─────────────────┘     └──────────────────┘     └─────────┬────────┘
                                                               │
                                                    ┌──────────▼─────────┐
                                                    │ Validation Agent   │
                                                    │ contracts, data,   │
                                                    │ tests, security    │
                                                    └──────────┬─────────┘
                                                               │
                                                    ┌──────────▼─────────┐
                                                    │ Human approval     │
                                                    │ before release     │
                                                    └──────────┬─────────┘
                                                               │
                                                    ┌──────────▼─────────┐
                                                    │ Operations view    │
                                                    │ logs, status,      │
                                                    │ alerts             │
                                                    └────────────────────┘

        Mock REST API       Mock SQL DB       HL7 v2 / flat-file feed
               └──────────────────┬──────────────────┘
                                  │
                         Integration adapters
```

### Proposed agent responsibilities

  -----------------------------------------------------------------------
  Agent             Inputs            Main              Expected output
                                      responsibility    
  ----------------- ----------------- ----------------- -----------------
  Discovery         OpenAPI docs,     Inspect           Normalised system
                    schemas, sample   interface,        profile
                    files/messages    fields, types and 
                                      dependencies      

  Design            Source/target     Recommend         Integration plan,
                    profiles and user integration       mapping and API
                    goal              pattern and field contract
                                      mappings          

  Code Generation   Approved plan and Generate adapter, Versioned code
                    mapping           transformation    artefacts
                                      and tests         

  Validation        Generated         Run contract,     Test report and
                    artefacts and     data and security issues
                    test data         checks            

  Operations        Approved running  Track health,     Status, logs and
                    integration       failures and      alerts
                                      execution         
  -----------------------------------------------------------------------

**Guardrail:** Agents should produce structured outputs. Validate those
outputs against schemas before using them. Do not execute arbitrary
model-generated code directly; generate into a controlled workspace,
inspect it, run tests in an isolated environment and require approval
before release.

## 5. Suggested technology choices

The brief says any language or framework may be used; Azure and .NET
Core are preferred.

  -----------------------------------------------------------------------
  Layer                   Possible choice         Notes
  ----------------------- ----------------------- -----------------------
  Frontend                React                   System setup, mapping
                                                  review and run
                                                  dashboard

  API/backend             FastAPI or .NET Core    Choose one primary
                                                  backend

  Agent workflow          LangGraph or a simple   Keep workflow
                          explicit state machine  observable and
                                                  reproducible

  LLM                     Approved hosted model   Use structured outputs
                          or local model          and record
                                                  model/version

  Database                PostgreSQL or SQLite    Store runs, mappings
                          for prototype           and audit events

  Healthcare format       HL7 FHIR; HL7 v2 parser Use the relevant public
                          for message input       specifications

  API contract            OpenAPI                 Describe generated or
                                                  mock REST endpoints

  Testing                 Pytest / xUnit plus     Test transformations
                          contract tests          and interfaces

  Deployment              Local Docker; Azure if  Deployment is secondary
                          time permits            to a reliable demo
  -----------------------------------------------------------------------

Do not introduce multiple frameworks unless they solve a clear problem.
A small, working, testable system is better than a complex architecture
that cannot be demonstrated.

## 6. Build roadmap

The hackathon brief describes a **15-day build sprint**. The schedule
below is a suggested sequence of work, not an additional official
deadline.

### Phase 1 --- Understand and define (Day 1)

-   [ ] Read Challenge 01 carefully.
-   [ ] Agree on the three mock systems and their interfaces.
-   [ ] Define one end-to-end use case, such as transferring a synthetic
    patient record.
-   [ ] Define the source and target schemas.
-   [ ] Decide what counts as a successful integration.
-   [ ] Agree on the technology stack and team responsibilities.

**Exit condition:** Everyone can explain the problem, demo scenario and
expected output.

### Phase 2 --- Build mock systems (Days 2--3)

-   [ ] Implement a REST patient service.
-   [ ] Create a SQL laboratory database with synthetic records.
-   [ ] Create an HL7 v2 message or flat-file feed.
-   [ ] Provide sample data and interface documentation.
-   [ ] Add deliberately different field names and formats to make
    mapping meaningful.
-   [ ] Write a manual adapter for one integration to establish a
    baseline.

**Exit condition:** A developer can access each mock system and manually
integrate at least one pair.

### Phase 3 --- Discovery (Days 4--5)

-   [ ] Build parsers/readers for OpenAPI, SQL schema and sample
    message/file inputs.
-   [ ] Extract fields, types, required/optional status and sample
    values.
-   [ ] Convert findings into a common system-profile format.
-   [ ] Show the discovered profile in the UI or CLI.
-   [ ] Test discovery against known expected schemas.

**Exit condition:** The system can produce a reliable, structured
profile for each mock system.

### Phase 4 --- Design and mapping (Days 6--7)

-   [ ] Define the target canonical/FHIR-aligned representation for the
    chosen use case.
-   [ ] Propose source-to-target field mappings.
-   [ ] Identify missing, ambiguous and incompatible fields.
-   [ ] Recommend an integration pattern (for example API-to-API,
    database adapter or message transformation).
-   [ ] Generate an OpenAPI contract where appropriate.
-   [ ] Add a human review step for mappings and design decisions.

**Exit condition:** A reviewer can inspect and approve an integration
plan before code generation.

### Phase 5 --- Code generation (Days 8--9)

-   [ ] Generate an adapter from an approved plan.
-   [ ] Generate data transformation logic.
-   [ ] Generate unit/contract tests.
-   [ ] Store generated artefacts with run/version identifiers.
-   [ ] Add deterministic templates and validation rather than relying
    on free-form code generation alone.
-   [ ] Run the generated adapter against mock systems.

**Exit condition:** At least one generated integration runs successfully
on synthetic data.

### Phase 6 --- Validation and recovery (Days 10--11)

-   [ ] Validate required fields and data types.
-   [ ] Validate API/message contracts.
-   [ ] Test missing, malformed, duplicate and unexpected values.
-   [ ] Compare source and destination records for correctness.
-   [ ] Capture test results and error explanations.
-   [ ] Allow the agent to propose a correction, but re-run tests and
    require approval.
-   [ ] Test failure handling and retry behaviour where relevant.

**Exit condition:** The prototype can demonstrate both a successful
integration and a detected failure.

### Phase 7 --- Innovation and operations (Day 12)

Choose a small number of features that can be completed and
demonstrated:

-   [ ] Confidence-labelled field mapping.
-   [ ] Integration-pattern recommendation with an explanation.
-   [ ] Schema-change detection and suggested mapping update.
-   [ ] Integration run history, logs and status.
-   [ ] Clear human approval gates.

**Exit condition:** At least one differentiating feature works end to
end. Avoid adding features that destabilise the core flow.

### Phase 8 --- Responsible AI and security (Day 13)

-   [ ] Confirm that all data is synthetic/public and contains no real
    patient information.
-   [ ] Mask sensitive-looking values in logs and demo output.
-   [ ] Keep credentials outside source code.
-   [ ] Add input validation and access controls appropriate to the
    prototype.
-   [ ] Record agent decisions, model/tool use and approvals.
-   [ ] Document failure modes, limitations and human oversight.
-   [ ] Prepare the one-page Responsible AI note.

**Exit condition:** The team can explain what data is used, what
safeguards exist and what the prototype does not guarantee.

### Phase 9 --- Evidence and packaging (Day 14)

-   [ ] Measure manual baseline time for the same integration.
-   [ ] Measure agent-assisted workflow time using the same start/end
    definitions.
-   [ ] Measure field-mapping correctness and test pass rate.
-   [ ] Repeat runs where possible and report the sample size.
-   [ ] Record failures and limitations; do not hide them.
-   [ ] Prepare the architecture diagram and solution deck.
-   [ ] Record the demo video.

**Exit condition:** Every performance claim in the presentation has
supporting evidence.

### Phase 10 --- Rehearse and submit (Day 15)

-   [ ] Run the demo from a clean environment.
-   [ ] Check repository setup instructions.
-   [ ] Verify that synthetic data and required configuration are
    included.
-   [ ] Rehearse the 7-minute pitch and 3-minute live demo.
-   [ ] Prepare answers to likely technical and business questions.
-   [ ] Submit the complete pack before the official deadline.

**Exit condition:** Another team member can clone the repository, follow
the README and run the demo.

------------------------------------------------------------------------

## 7. How to measure whether it works

The brief asks teams to show time and consistency gains compared with
hand-built integrations. Define measurements before running the
comparison.

  -----------------------------------------------------------------------
  Measurement                         Suggested definition
  ----------------------------------- -----------------------------------
  Integration time                    Elapsed active time from receiving
                                      system specifications to a passing
                                      integration

  Mapping correctness                 Correct approved field mappings ÷
                                      total evaluated mappings

  Test pass rate                      Passed tests ÷ total executed tests

  Record reconciliation               Records matching expected
                                      destination values ÷ records
                                      processed

  Human intervention                  Number of review actions or
                                      corrections required

  Failure handling                    Whether invalid input is detected,
                                      explained and prevented from
                                      silently passing
  -----------------------------------------------------------------------

For a fair comparison:

1.  Use the same source/target systems and requirements.
2.  Give both approaches the same acceptance tests.
3.  Record manual and agent-assisted time consistently.
4.  Report the number of runs and test cases.
5.  Include failed attempts and human correction time.
6.  Do not present illustrative or expected numbers as measured results.

## 8. Responsible AI and healthcare safeguards

-   Use synthetic data only; the hackathon brief explicitly prohibits
    personal data.
-   Do not send real PHI to an LLM or include it in logs.
-   Treat model-generated mappings and code as proposals, not trusted
    facts.
-   Validate data types, required fields, identifiers and message
    contracts.
-   Require human approval for ambiguous mappings and before deployment.
-   Keep credentials in environment variables or a secrets manager.
-   Restrict access to system configuration and generated artefacts.
-   Log agent actions and approvals without exposing sensitive data.
-   Explain limitations, uncertainty and known failure cases.

This is a hackathon prototype, not a certified production healthcare
integration platform.

## 9. Repository structure

A possible starting structure:

``` text
agentic-healthcare-integration/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── integration-workflow.md
│   ├── data-dictionary.md
│   └── responsible-ai.md
├── frontend/
├── backend/
│   ├── api/
│   ├── orchestration/
│   ├── agents/
│   │   ├── discovery/
│   │   ├── design/
│   │   ├── code_generation/
│   │   ├── validation/
│   │   └── operations/
│   ├── connectors/
│   │   ├── rest/
│   │   ├── sql/
│   │   ├── hl7/
│   │   └── files/
│   ├── models/
│   └── tests/
├── mock_systems/
│   ├── patient_api/
│   ├── laboratory_db/
│   └── hospital_records/
├── synthetic_data/
├── generated/
├── evaluation/
│   ├── manual_baseline/
│   ├── benchmark_results/
│   └── scripts/
├── demo/
└── .env.example
```

This is a suggested structure; adjust it to the team's language and
framework.

## 10. Submission requirements

### Hackathon brief --- page 13

One submission pack per team:

  -----------------------------------------------------------------------
  Item                                Requirement
  ----------------------------------- -----------------------------------
  Solution deck                       Up to 10 slides: problem, approach,
                                      architecture, results, Responsible
                                      AI and next steps

  Demo video                          Up to 3 minutes, shared as a link

  Code repository                     GitHub or similar, with README and
                                      setup steps

  Architecture diagram                One page showing components, data
                                      flows and AI models

  Responsible AI note                 One page covering data used,
                                      privacy, bias, limitations and
                                      safeguards
  -----------------------------------------------------------------------

Submission details in the brief:

-   **Email:** Monika.Rawal@exlservice.com
-   **Subject:** `EXL Hackathon | Team name | Challenge 01`
-   **Send from:** A team member's UCD email address
-   **Deadline stated in the brief:** 13 November 2026, 23:59 Irish time
    (marked proposed / to be confirmed in the document).

The brief also says to declare AI tools and any existing code used.
Confirm any proposed dates or terms with the organisers if they have
issued an update.

## 11. Judging criteria

The official weights in the brief (page 14) are:

  Criterion              Weight
  -------------------- --------
  Business Impact           30%
  Technical Approach        25%
  Innovation                20%
  Responsible AI            15%
  Presentation & Q&A        10%

Business Impact is about user benefit and measurable success. Technical
Approach is about suitable data/AI methods and feasibility. Innovation
is about a distinct improvement over alternatives. Responsible AI covers
privacy, security, bias, limitations and safeguards. Presentation & Q&A
covers clarity and evidence.

## 12. Team working agreements

-   Keep the first end-to-end use case small.
-   Agree on input/output schemas before splitting agent work.
-   Keep generated code separate from application source code.
-   Make every agent's inputs, outputs and errors inspectable.
-   Version generated artefacts and record the model/tool configuration
    used.
-   Do not claim an agent completed an action unless the action was
    actually executed and verified.
-   Keep a working demo at the end of every development phase.
-   Prioritise a reliable end-to-end integration over many disconnected
    features.

## 13. First tasks to start today

1.  Create the repository using the proposed structure.
2.  Assign an owner for mock systems, orchestration/agents, frontend and
    evaluation/documentation.
3.  Agree on the three-system demo scenario.
4.  Define the common patient/clinical data model and sample synthetic
    records.
5.  Build one manual integration and write its acceptance tests.
6.  Only then implement discovery and agent-assisted design.

------------------------------------------------------------------------

## References

-   **EXL Data & AI Hackathon 2026 with UCD**, supplied programme
    proposal:
    -   Page 6: Challenge 01 --- Agentic healthcare integration.
    -   Page 10--11: Timeline and student roadmap.
    -   Page 12: Grand finale format.
    -   Page 13: Submission requirements.
    -   Page 14: Judging criteria.
    -   Page 16: FAQs, including synthetic/public data and AI-tool
        declaration.

**This README combines the official Challenge 01 requirements with
clearly labelled team implementation suggestions. Where the brief is
silent, the proposed design and roadmap are recommendations rather than
EXL requirements.**
