-- The file the decision gate annotates.
--
-- This is the change an engineer is proposing: dropping `promo_code` from the
-- analytics view. `dhdr` decides whether that is safe by reading downstream
-- lineage from DataHub, and the certificate arrives as a code-scanning
-- annotation on this file — see .github/workflows/dhdr-gate.yml and
-- https://github.com/Laolex/datahub-decision-records/pull/1
--
-- dhdr proposes changes and never applies them; nothing here is executed.

CREATE OR REPLACE VIEW analytics.order_history AS
SELECT
    order_id,
    customer_id,
    order_total,
    -- promo_code            <- proposed for removal
    created_at
FROM order_entry.orders;
