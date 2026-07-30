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

export default function GaReadinessAudit() {
  return (
    <Stack gap={24} style={{ padding: 24, maxWidth: 1100 }}>
      <Stack gap={8}>
        <H1>General Availability Readiness Audit</H1>
        <Text tone="secondary">
          Authority: 27_V1_GA_APPROVAL · Assume Closed Beta completed · Evidence-only · Audit-only ·
          2026-07-30
        </Text>
        <Row gap={8} style={{ flexWrap: "wrap" }}>
          <Pill tone="deleted">Decision: REJECTED</Pill>
          <Pill tone="deleted">Evidence incomplete</Pill>
          <Pill tone="deleted">No GA identity</Pill>
          <Pill tone="warning">Beta assumed; report missing</Pill>
        </Row>
      </Stack>

      <Callout tone="danger" title="GA not approvable">
        Assuming Closed Beta finished does not create the Closed Beta Report, Product Acceptance
        Report, CI Report, Integrity Report, Risk Assessment, or joint Dev/QA/PO approval record.
        Live packaging remains 0.1.5.dev0; git has no commits/tags; latest seal is 0.1.4 — not a
        coherent 1.0.0 GA identity.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="FAIL" label="Integrity" tone="danger" />
        <Stat value="MISSING" label="Product Acc." tone="danger" />
        <Stat value="MISSING" label="Beta Report" tone="danger" />
        <Stat value="BLANK" label="Approval Record" tone="danger" />
      </Grid>

      <Divider />

      <H2>Required evidence (27)</H2>
      <Table
        headers={["Artifact", "Present?", "Same identity?"]}
        rows={[
          ["Release Integrity Report", "NO", "—"],
          ["Engineering Acceptance Report", "NO", "—"],
          ["Product Acceptance Report", "NO", "—"],
          ["Release CI Report", "NO", "—"],
          ["Closed Beta Report", "NO*", "Assumed done; no archive"],
          ["Risk Assessment", "NO", "—"],
          ["Release Notes", "YES (RC)", "Not GA 1.0.0 / live tree"],
          ["Git commit + tag", "NO", "main: no commits yet"],
          ["GA seal 1.0.0", "NO", "Seal on disk: 0.1.4"],
        ]}
        rowTone={[
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "warning",
          "danger",
          "danger",
        ]}
      />

      <H2>Approval record</H2>
      <Table
        headers={["Field", "Value"]}
        rows={[
          ["Release version", "UNDEFINED (live 0.1.5.dev0; no 1.0.0)"],
          ["Git commit", "NONE (no commits on main)"],
          ["Git tag", "NONE"],
          ["Approval date", "BLANK"],
          ["Development", "BLANK"],
          ["QA", "BLANK"],
          ["Product Owner", "BLANK"],
          ["Final decision", "REJECTED (this audit)"],
        ]}
        rowTone={[
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
        ]}
      />

      <Callout tone="danger" title="5. Final GA Decision">
        REJECTED — Critical evidence and identity gaps block GA. Cannot approve with Known
        Limitations while Critical risks remain and Required Evidence is absent.
      </Callout>
    </Stack>
  );
}
