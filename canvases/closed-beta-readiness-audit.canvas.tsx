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

export default function ClosedBetaReadinessAudit() {
  return (
    <Stack gap={24} style={{ padding: 24, maxWidth: 1100 }}>
      <Stack gap={8}>
        <H1>Closed Beta Readiness Audit</H1>
        <Text tone="secondary">
          Authority: 26_CLOSED_BETA_PLAN · Assume RC2 approved · GA not judged · Audit-only ·
          2026-07-30
        </Text>
        <Row gap={8} style={{ flexWrap: "wrap" }}>
          <Pill tone="warning">READY WITH LIMITATIONS</Pill>
          <Pill tone="success">RC2 assumed PASS</Pill>
          <Pill tone="warning">Risk: Medium (managed)</Pill>
        </Row>
      </Stack>

      <Callout tone="warning" title="Suitable for limited external beta">
        Under the RC2-approved assumption, engineering entry criteria are treated as met.
        Product fitness for Closed Beta is acceptable only with an explicit limited scope:
        Object Workflow primary path, disclosed Known Limitations, facilitated install/first-run,
        and plugin install/remove excluded from mandatory participant tasks.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="YES*" label="Product core path" tone="success" />
        <Stat value="OK" label="Known Limitations" tone="success" />
        <Stat value="SCOPED" label="Beta scope" tone="warning" />
        <Stat value="MED" label="Risk level" tone="warning" />
      </Grid>

      <Divider />

      <H2>Beta readiness snapshot</H2>
      <Table
        headers={["Area", "Suitable?", "Constraint"]}
        rows={[
          ["Installation", "With facilitation", "Wheel/source; Python 3.12; brief participants"],
          ["First-run / OW", "Yes*", "Must click Object Workflow — not Create Project"],
          ["Workspace", "Yes", "Create/open/recent/reopen documented"],
          ["Batch", "Partial", "UI present; Batch Guide stub"],
          ["Plugins", "Observe only", "No Install UI; SDK/CLI for technical cohort only"],
          ["Docs", "Partial", "Getting Started + User Guide OK; Batch/Plugin stubs"],
          ["Stability claim", "RC2 assumed", "UI/real_model Not Verified — disclose"],
        ]}
        rowTone={[
          "warning",
          "warning",
          "success",
          "warning",
          "warning",
          "warning",
          "warning",
        ]}
      />

      <H2>Must-limit before inviting users</H2>
      <Stack gap={12}>
        <Card>
          <CardHeader trailing={<Pill tone="warning">Limitation</Pill>}>
            Dual welcome product paths
          </CardHeader>
          <CardBody>
            <Text size="small">
              Briefing mandatory: Object Workflow button only. Known Limitations §2 Intentional.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning">Limitation</Pill>}>
            Plugin install/remove not in UI
          </CardHeader>
          <CardBody>
            <Text size="small">
              26 scenario is “if supported” — mark unsupported for general beta; technical track
              optional via Plugin SDK.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning">Limitation</Pill>}>
            Batch / Plugin end-user guides stubbed
          </CardHeader>
          <CardBody>
            <Text size="small">
              Rely on User Guide overview + facilitator notes; do not claim full doc coverage.
            </Text>
          </CardBody>
        </Card>
      </Stack>

      <Callout tone="warning" title="5. Release Recommendation">
        READY WITH LIMITATIONS — start Closed Beta only under a constrained charter aligned to
        Known Limitations; do not treat outcomes as GA approval.
      </Callout>
    </Stack>
  );
}
