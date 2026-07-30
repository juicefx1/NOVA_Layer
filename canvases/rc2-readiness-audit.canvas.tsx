import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

export default function Rc2ReadinessAudit() {
  return (
    <Stack gap={24} style={{ padding: 24, maxWidth: 1100 }}>
      <Stack gap={8}>
        <H1>RC2 Readiness Audit</H1>
        <Text tone="secondary">
          Authority: 25_RC2_CHECKLIST · Gates 21–24 (Engineering only) · GA ignored ·
          Audit-only · 2026-07-30
        </Text>
        <Row gap={8} style={{ flexWrap: "wrap" }}>
          <Pill tone="deleted">Decision: REJECTED</Pill>
          <Pill tone="deleted">Integrity FAIL</Pill>
          <Pill tone="deleted">CI FAIL</Pill>
          <Pill tone="warning">Acceptance PARTIAL</Pill>
          <Pill tone="warning">UX WARN</Pill>
        </Row>
      </Stack>

      <Callout tone="danger" title="Closed Beta not cleared">
        Current tree is a development build (`0.1.5.dev0`) without git identity, without an
        RC2-versioned seal, without an archived Release CI report, and without required RC2
        deliverables (Engineering Acceptance Report, CI Report, Risk Assessment). Feature 13
        is neither Released nor Deferred.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="FAIL" label="Integrity" tone="danger" />
        <Stat value="PARTIAL" label="Eng. Acceptance" tone="warning" />
        <Stat value="FAIL" label="Release CI" tone="danger" />
        <Stat value="WARN" label="Engineering UX" tone="warning" />
      </Grid>

      <Divider />

      <H2>RC2 checklist (mandatory)</H2>
      <Table
        headers={["Gate", "Item", "Status", "Evidence"]}
        rows={[
          ["Integrity", "Release version defined", "FAIL", "docs v1.0 RC ≠ 0.1.5.dev0 ≠ seal 0.1.4; no 1.0.0-rc2"],
          ["Integrity", "Release identity established", "FAIL", "No .git → no commit/tag"],
          ["Integrity", "Artifacts identified", "FAIL*", "0.1.4 seal on disk; not live tree / not RC2"],
          ["Integrity", "Release notes prepared", "PASS*", "Approved notes; seal-centric, stale vs live"],
          ["Acceptance", "Features 08–12 accepted", "LIKELY*", "22 matrix Accepted; tests exist; no Eng Acc Report"],
          ["Acceptance", "Feature 13 Released|Deferred", "FAIL", "22: Not Released / Pending; no Deferred decision"],
          ["CI", "Pipeline + tests + regression", "FAIL", "ci.yml offline only; no archived run for candidate"],
          ["CI", "Package + version validated", "FAIL", "No CI package stage; no sdist; version mismatch"],
          ["UX", "OW / workspace / progress / errors", "PASS*", "UI present; Known Limitations disclose dual entry"],
          ["UX", "No critical UI blockers (RC2)", "WARN", "Plugin GUI deferred (documented); welcome not primary"],
          ["Docs", "Required RC2 deliverables", "FAIL", "Missing Eng Acc Report, CI Report, Risk Assessment"],
        ]}
        rowTone={[
          "danger",
          "danger",
          "danger",
          "warning",
          "warning",
          "danger",
          "danger",
          "danger",
          "warning",
          "warning",
          "danger",
        ]}
      />

      <H2>Critical blockers (RC2)</H2>
      <Stack gap={12}>
        <Card>
          <CardHeader trailing={<Pill tone="deleted">Critical</Pill>}>
            No RC2 release identity
          </CardHeader>
          <CardBody>
            <Text size="small">
              HAS_GIT=no · live 0.1.5.dev0 · latest seal 0.1.4 · Integrity/25 require defined
              version + identity for an RC candidate.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="deleted">Critical</Pill>}>
            Release CI evidence absent
          </CardHeader>
          <CardBody>
            <Text size="small">
              Test Report explicitly: no CI transcript for seal or live tree. 23 + 25 require
              completed pipeline, package/version validation, archived CI report.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="deleted">Critical</Pill>}>
            Feature 13 undecided
          </CardHeader>
          <CardBody>
            <Text size="small">
              RC2 mandates Released or Deferred. Matrix: Pending / Not Released. Code + notes
              mention Automation; no formal deferral.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="deleted">Critical</Pill>}>
            Required deliverables incomplete
          </CardHeader>
          <CardBody>
            <Text size="small">
              Missing Engineering Acceptance Report, CI Report, Risk Assessment (25 Required
              Deliverables).
            </Text>
          </CardBody>
        </Card>
      </Stack>

      <Callout tone="danger" title="5. Final RC2 Decision">
        REJECTED — not ready for Release Candidate 2 / Closed Beta entry.
      </Callout>
    </Stack>
  );
}
