-- The file the decision gate annotates.
--
-- This is the pipeline as it stands on `main`: `promo_code` is still selected.
--
-- The proposed change lives on the `demo/decision-gate` branch, which removes
-- that column. `dhdr` decides whether the removal is safe by reading downstream
-- lineage from DataHub, and the certificate arrives as a code-scanning
-- annotation on the removed line — see .github/workflows/dhdr-gate.yml and
-- https://github.com/Laolex/datahub-decision-records/pull/1
--
-- dhdr proposes changes and never applies them; nothing here is executed.

CREATE OR REPLACE VIEW analytics.order_history AS
SELECT
    order_id,
    customer_id,
    order_total,
    promo_code,
    created_at
FROM order_entry.orders;
