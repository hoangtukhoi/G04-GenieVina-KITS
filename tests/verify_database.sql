-- Run AFTER the default seed. All test mutations are rolled back.
BEGIN;
CREATE FUNCTION pg_temp.expect_failure(statement TEXT, expected_state TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE <> expected_state THEN RAISE; END IF;
        RETURN;
    END;
    RAISE EXCEPTION 'Statement unexpectedly succeeded: %', statement;
END;
$$;

SELECT pg_temp.expect_failure('DELETE FROM customers WHERE id = 1', '23503');
SELECT pg_temp.expect_failure('DELETE FROM customers WHERE id = 6', '23503');
SELECT pg_temp.expect_failure($q$INSERT INTO orders(customer_id,package_name,amount) VALUES (1,'TEST',0)$q$, '23514');
SELECT pg_temp.expect_failure($q$INSERT INTO orders(customer_id,package_name,amount) VALUES (999999,'TEST',1)$q$, '23503');
SELECT pg_temp.expect_failure($q$INSERT INTO ai_results(customer_id,type,created_at) VALUES (1,'QUOTE','2000-01-01')$q$, '23514');
SELECT pg_temp.expect_failure($q$UPDATE customers SET signed_up_at = '2099-01-01' WHERE id = 1$q$, '23514');
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'PENDING', paid_at = NULL WHERE id = 1$q$, '23514');
SELECT pg_temp.expect_failure($q$INSERT INTO customers(customer_code,name,country,signup_method,signed_up_at)
    VALUES ('SYN-00001','Duplicate','VN','EMAIL',now())$q$, '23505');

SET LOCAL app.member_id = '';
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'PAID', paid_at = now() WHERE id = 7$q$, '23514');
SET LOCAL app.member_id = '3';
SET LOCAL app.change_reason = 'Test VIEWER';
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'PAID', paid_at = now() WHERE id = 7$q$, '23514');
SET LOCAL app.member_id = '2';
SET LOCAL app.change_reason = '';
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'PAID', paid_at = now() WHERE id = 7$q$, '23514');
SET LOCAL app.change_reason = 'Integration test';
UPDATE orders SET status = 'PAID', paid_at = now() WHERE id = 7;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM order_status_histories WHERE order_id = 7
        AND previous_status = 'PENDING' AND new_status = 'PAID' AND changed_by = 2
        AND reason = 'Integration test') THEN RAISE EXCEPTION 'Missing automatic history'; END IF;
END $$;
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'FAILED', paid_at = NULL WHERE id = 7$q$, '23514');
UPDATE orders SET status = 'REFUNDED', refunded_at = now() WHERE id = 7;
SELECT pg_temp.expect_failure($q$UPDATE orders SET status = 'PAID', refunded_at = NULL WHERE id = 7$q$, '23514');
INSERT INTO orders(customer_id, package_name, amount) VALUES (6, 'SEQUENCE_TEST', 100);

DO $$ BEGIN
    IF (SELECT COUNT(*) FROM customers) <> 60 THEN RAISE EXCEPTION 'Unexpected customer count'; END IF;
    IF EXISTS (SELECT 1 FROM orders WHERE status = 'PAID'
        AND (paid_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = DATE '2026-11-24') THEN
        RAISE EXCEPTION 'Expected a zero revenue day';
    END IF;
    IF (SELECT COUNT(*) FROM orders WHERE id > 84) <> 1 THEN RAISE EXCEPTION 'Identity sequence not reset'; END IF;
END $$;
ROLLBACK;
