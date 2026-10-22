"""Restricted-role reported-spend acceptance in the existing isolated PG harness."""

from scripts.check_rule_pilot_postgres import main

if __name__ == "__main__":
    main(reported_spend_test=True)
