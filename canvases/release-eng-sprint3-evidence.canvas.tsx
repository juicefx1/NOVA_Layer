import {
  Callout,
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

export default function ReleaseEngSprint3Evidence() {
  return (
    <Stack gap={24} style={{ padding: 24, maxWidth: 1100 }}>
      <Stack gap={8}>
        <H1>Release Engineering Sprint 3</H1>
        <Text tone="secondary">
          Focus: Release Evidence · Audit only · No CI · No artifacts · No app changes · 2026-07-30
        </Text>
        <Row gap={8} style={{ flexWrap: "wrap" }}>
          <Pill tone="warning">Partial proxies</Pill>
          <Pill tone="deleted">Named reports missing</Pill>
          <Pill tone="deleted">Beta unevidenced</Pill>
          <Pill tone="deleted">Approvals blank</Pill>
        </Row>
      </Stack>

      <Callout tone="danger" title="Evidence package incomplete">
        Policy docs and some RC proxies exist (Test Report, Known Limitations, Phase 1 acceptance,
        audit canvases). Formal Engineering/Product Acceptance Reports, Risk Assessment, Closed
        Beta Report, CI Report, Integrity Report, and filled Approval Record are absent for a
        shared release identity.
      </Callout>

      <Grid columns={5} gap={12}>
        <Stat value="PROXY" label="Eng Acc" tone="warning" />
        <Stat value="NO" label="Product Acc" tone="danger" />
        <Stat value="NO" label="Risk Assess" tone="danger" />
        <Stat value="NO" label="Beta Report" tone="danger" />
        <Stat value="BLANK" label="Approvals" tone="danger" />
      </Grid>

      <Divider />

      <H2>Required reports (27 + 22 + 26)</H2>
      <Table
        headers={["Report", "Status"]}
        rows={[
          ["Engineering Acceptance Report", "MISSING (matrix + tests only)"],
          ["Product Acceptance Report", "MISSING"],
          ["Closed Beta Report", "MISSING"],
          ["Risk Assessment", "MISSING"],
          ["Release Integrity Report", "MISSING (audits ≠ archive)"],
          ["Release CI Report", "MISSING (out of Sprint 3 impl)"],
          ["Release Notes", "PRESENT (RC-scoped)"],
          ["Approval Record", "BLANK"],
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
        ]}
      />
    </Stack>
  );
}
