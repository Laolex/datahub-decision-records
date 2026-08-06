-- The file the decision gate annotates.
--
-- On `main`, `promo_code` is still selected. The `demo/decision-gate` branch
-- proposes removing it, and that one-line difference is the change under
-- decision. `dhdr` reads downstream lineage from DataHub to decide whether the
-- removal is safe, and the certificate arrives as a code-scanning annotation on
-- that line — see .github/workflows/dhdr-gate.yml and
-- https://github.com/Laolex/datahub-decision-records/pull/1
--
-- dhdr proposes changes and never applies them; nothing here is executed.

CREATE OR REPLACE VIEW analytics.order_history AS
SELECT
    order_id,
    customer_id,
    order_total,
    -- promo_code,          <- proposed for removal
    created_at
FROM order_entry.orders;
