"""End-to-end checks that database errors reach the client with module-specific messages."""
import psycopg
import pytest

from tests.test_customers_api import assert_response, auth


def message(response, status):
    assert_response(response, status)
    return response.json()['message']


def test_trigger_and_fk_errors_keep_specific_messages(client):
    assert message(client.delete('/api/customers/1', headers=auth()), 409) == \
        'Customer has related orders or AI results and cannot be deleted'
    assert message(client.patch('/api/customers/1', json={'signedUpAt': '2099-01-01T00:00:00+07:00'},
                                headers=auth()), 409) == 'Customer signup date conflicts with existing events'


@pytest.mark.parametrize('statement,constraint', [
    ("INSERT INTO orders(customer_id, package_name, amount) VALUES (999999, 'X', 1)", 'customer_event_customer_exists'),
    ("INSERT INTO ai_results(customer_id, type, created_at) VALUES (1, 'QUOTE', '2000-01-01')", 'customer_event_after_signup'),
    ("INSERT INTO orders(customer_id, package_name, amount, status) VALUES (1, 'X', 1, 'PAID')", 'orders_initial_status'),
    ("UPDATE orders SET status = 'PAID', paid_at = now() WHERE id = (SELECT MIN(id) FROM orders WHERE status = 'FAILED')",
     'orders_valid_transition'),
])
def test_trigger_errors_expose_constraint_name(api_database, statement, constraint):
    with psycopg.connect(api_database) as connection:
        connection.execute("SET app.member_id = '1'; SET app.change_reason = 'test'")
        with pytest.raises(psycopg.errors.IntegrityError) as exc:
            connection.execute(statement)
        connection.rollback()
    assert exc.value.diag.constraint_name == constraint


def test_unknown_route_and_method_use_common_envelope(client):
    assert message(client.get('/api/does-not-exist'), 404) == 'Not Found'
    response = client.put('/api/customers', headers=auth())
    assert message(response, 405) == 'Method Not Allowed'
    assert 'allow' in response.headers
