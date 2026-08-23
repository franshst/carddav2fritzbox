# Feature Specification: Docker Swarm Deployment

**Feature Branch**: `002-docker-swarm-deployment`

**Created**: 2026-08-22

**Status**: Draft

**Input**: User description: "I have additional wishes in docker.md. Before integrating into the specs, please check if it is clear what I need, possibly amending requirements." (wishes captured and clarified in `docker.md`: containerized delivery of the sync for Docker Swarm with scheduled execution, failure email, secrets-based credentials, deployment script, and separate documentation)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scheduled unattended sync as a deployed stack (Priority: P1)

A home-network operator deploys the carddav2fritzbox sync as a service in their
Docker Swarm cluster. After a one-time deployment, the contact synchronization
runs automatically every night without any manual interaction. The operator no
longer needs to maintain a cron entry or a Python environment on the host.

**Why this priority**: This is the core value of the feature — turning the CLI
utility into an operationally self-sufficient, scheduled deployment. Without it,
none of the other stories have meaning.

**Independent Test**: Can be fully tested by deploying the provided stack
definition to a Swarm and verifying that the sync runs end-to-end on schedule
and produces the expected FritzBox phonebook result — delivers hands-off
operation.

**Acceptance Scenarios**:

1. **Given** a Swarm cluster with the stack deployed and valid configuration,
   **When** the scheduled trigger time arrives, **Then** the sync runs inside
   its own one-shot task/container and completes with exit code 0.
2. **Given** a deployed stack, **When** the scheduled run executes, **Then**
   the FritzBox address book reflects the current state of the configured
   CardDAV sources exactly as a manual run would produce.
3. **Given** the stack is deployed, **When** the schedule elapses again the
   next day, **Then** a new run starts automatically without any operator
   action.
4. **Given** the operator wants a different cadence, **When** they change the
   cron expression in the stack configuration and redeploy, **Then** subsequent
   runs follow the new schedule.

---

### User Story 2 - Email notification when a sync fails (Priority: P2)

When a scheduled sync fails (non-zero exit), the operator receives an email
containing the full captured output of the failed run plus its exit code, so
they can diagnose the problem without SSH-ing into the cluster. Successful runs
send nothing — the operator's inbox stays quiet unless attention is needed.

**Why this priority**: Unattended jobs that fail silently destroy trust in the
automation; timely diagnosis is essential once nobody watches the run.

**Independent Test**: Can be fully tested by forcing a sync failure in a
deployed stack and verifying an email arrives containing the complete output
and exit code — and by confirming no email is sent on success.

**Acceptance Scenarios**:

1. **Given** a deployed stack with mail settings configured, **When** a sync
   run exits with a non-zero code, **Then** an email is sent to the configured
   recipient containing the full captured output (stdout and stderr) of the run
   and its exit code.
2. **Given** a deployed stack, **When** a sync run succeeds (exit code 0),
   **Then** no email is sent.
3. **Given** the mail settings are misconfigured, **When** a sync fails,
   **Then** the failure of the notification itself does not mask the sync's
   non-zero outcome (the failed run remains observable in the platform logs).

---

### User Story 3 - Credentials supplied exclusively via Docker secrets (Priority: P2)

The operator provisions all sensitive values (FritzBox password, CardDAV source
passwords, FTP password if picture sync is used, SMTP credentials for the
failure email) as Docker secrets. No password ever appears in the stack file,
the mounted configuration file, the image, or version control. An example
shell script demonstrates creating all required secrets and deploying the
stack in one go.

**Why this priority**: Secure credential handling is a constitution principle;
without it the deployment could not be considered production-usable.

**Independent Test**: Can be fully tested by running the example script against
a fresh cluster and verifying the sync works while inspecting that no secret
value appears in the compose definition, image layers, or logs.

**Acceptance Scenarios**:

1. **Given** the example script is executed with the required secret values,
   **When** it finishes, **Then** all required secrets exist in the Swarm and
   the stack is deployed.
2. **Given** secrets are provisioned, **When** the sync runs, **Then** it
   authenticates successfully using the secret-provided credentials.
3. **Given** the deployment artifacts, **When** inspected, **Then** no secret
   value is present in the stack file, the container image, or the example
   script itself.

---

### User Story 4 - Separate documentation for Docker and Swarm usage (Priority: P3)

An operator who only wants to run the container once (or under their own
scheduler) can follow a plain-Docker usage document; an operator who wants the
full scheduled Swarm setup can follow a separate Swarm document. Both live in
the `docker/` directory alongside the deliverables.

**Why this priority**: Documentation enables adoption but each document can be
written after the working deliverables exist.

**Independent Test**: Can be fully tested by a new user following either
document alone and completing the corresponding deployment path without
consulting other project files.

**Acceptance Scenarios**:

1. **Given** only the plain-Docker document, **When** a user follows it,
   **Then** they can build/run the container and supply configuration and
   secrets correctly.
2. **Given** only the Swarm document, **When** a user follows it,
   **Then** they can create the secrets, deploy the stack, configure the
   schedule, and verify a run.

---

### Edge Cases

- What happens when the network to the FritzBox or a CardDAV source is down at
  the scheduled time? → The run fails; per US2 the operator receives the full
  output by email, and the next scheduled run retries normally.
- What happens when a required secret is missing at start-up? → The run fails
  fast before touching the FritzBox, with a clear message naming the missing
  item; the failure triggers the US2 email.
- What happens when the mail settings themselves are wrong? → Per US2 the
  delivery problem must not hide the original failure; the sync's non-zero
  outcome stays visible in platform logs.
- What happens when two deployments/schedules overlap (a run still in progress
  when the next trigger fires)? → Runs must not corrupt each other's upload;
  overlap behaviour is defined and documented.
- What happens when the config file references more CardDAV sources than
  secrets were created for? → Missing credentials fail validation with a clear
  error rather than a partial silent sync.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a container image that runs the existing
  carddav2fritzbox sync unchanged, given the same configuration inputs as the
  CLI utility.
- **FR-002**: System MUST provide a wrapper around the sync that treats any
  non-zero sync exit code as a failure and any zero exit code as success.
- **FR-003**: On failure, the wrapper MUST send an email to a configurable
  recipient containing the full captured output (stdout and stderr) of the run
  and the exit code.
- **FR-004**: On success, the wrapper MUST NOT send an email.
- **FR-005**: All mail settings (recipient, server, and server credentials)
  MUST be configurable via configuration backed by environment/secret input.
- **FR-006**: The deployment MUST execute the sync on a schedule with a daily
  default, where the schedule is expressed as a configurable cron expression in
  the stack definition.
- **FR-007**: All sensitive values (FritzBox password, CardDAV source
  passwords, FTP password if used, SMTP credentials) MUST be supplied as Docker
  secrets and injected into the run as environment variables that override
  config-file values per the documented precedence rules.
- **FR-008**: The non-secret configuration (`config.ini` without embedded
  credentials) MUST be provided to the container without being baked into the
  image.
- **FR-009**: A single example script MUST exist that creates all required
  Docker secrets and deploys the stack.
- **FR-010**: All Docker/Swarm deliverables MUST reside in the `docker/`
  directory of the repository.
- **FR-011**: Usage documentation MUST be provided separately for plain Docker
  usage and for Swarm stack deployment within the `docker/` directory.
- **FR-012**: The container run MUST be non-interactive and suitable for
  repeated scheduled execution.
- **FR-013**: Secret values MUST NOT appear in the stack file, the image, the
  example script, or container logs.
- **FR-014**: A missing required secret MUST cause the run to fail fast with a
  clear, actionable error identifying what is missing.
- **FR-015**: Failure to send the notification email MUST NOT change the
  observed failure outcome of the underlying sync run.

### Key Entities *(include if feature involves data)*

- **Deployment Stack Definition**: describes the sync service, its scheduling,
  its configuration mounts, and its secret references; the single artifact an
  operator deploys to the cluster.
- **Secret Set**: named cluster-level secrets corresponding one-to-one to the
  credential environment inputs already supported by the utility (FritzBox,
  per-source CardDAV, FTP, SMTP).
- **Wrapper Configuration**: mail recipient and mail transport settings needed
  solely by the failure-notification wrapper; distinct from sync configuration.
- **Run Output Record**: the captured stdout/stderr and exit code of one sync
  execution; input to the failure email and to platform logs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Deploying the stack from the provided artifacts takes an operator
  under 15 minutes, including secret creation, using only the shipped
  documentation and example script.
- **SC-002**: In a 7-day observation window with healthy sources, 100% of
  scheduled runs execute without operator intervention and produce a FritzBox
  phonebook identical to a manual run with the same inputs.
- **SC-003**: Every induced sync failure results in exactly one notification
  email delivered to the configured recipient containing the complete output
  and exit code, within 5 minutes of the run ending.
- **SC-004**: Zero secret values can be found in the stack definition, image,
  scripts, or logs (verified by inspection/search).
- **SC-005**: Changing the schedule via the stack configuration takes effect
  after redeployment without rebuilding the image.

## Assumptions

- Operators have a working Docker Swarm cluster with the swarm-cronjob
  mechanism available (or installable) and outbound SMTP access for failure
  notifications.
- The sync utility's existing configuration format, environment-variable
  overrides, and exit-code semantics remain authoritative; this feature wraps
  them and changes none of them.
- Default schedule is nightly; the exact default time is an operational choice
  documented in the stack file.
- One-shot execution per trigger (a fresh run each time) rather than a
  long-running daemon is the intended model.
- Building/publishing the image is part of development delivery; operators may
  build locally from the repository.
- Overlapping runs are prevented by design (a missed trigger is skipped rather
  than queued); this is documented.
