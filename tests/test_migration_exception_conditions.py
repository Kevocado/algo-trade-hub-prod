"""Every `EXCEPTION` guard in `market_sentiment_tool/supabase/migrations/` was checked against the
wrong SQLSTATE, and the migration that owns one of them is the reason production is red.

What happened on 2026-09-28: `20260415090000_signal_events_unification.sql` was applied by hand and
died with

    ERROR:  42P01: relation "crypto_signal_events" does not exist
    CONTEXT:  SQL statement "ALTER PUBLICATION supabase_realtime DROP TABLE crypto_signal_events"

The guard around that statement caught `undefined_object` and `invalid_parameter_value`. 42P01 is
`undefined_table`. `undefined_object` is 42704, which is undefined function/operator -- a different
class -- so the guard was a correct guard for a different error and the real one walked straight
through it. `undefined_object` is a real PL/pgSQL condition name, which is exactly why nothing
complained: this is not a typo a linter can see, it is a statement about which error a specific
command can raise, and it was wrong.

Note what that means for testing. The "do these condition names exist" check that seems like the
obvious general test PASSES on the broken file, because `undefined_object` is a legitimate
PL/pgSQL condition name. Catching this needs the semantic test: work out, from the shape of the
guarded statement, which SQLSTATEs that statement can actually raise, translate the guard's
condition names back through their SQLSTATEs, and require the guard to cover them. That is what
`test_every_exception_guard_covers_the_sqlstates_its_statement_can_raise` does, and it is the test
that fails if the bug is put back.

Both halves matter, so both are here:
  - the name-existence test, because a condition name that is not in PostgreSQL's list fails the
    migration at runtime with a confusing error, and it is free to check;
  - the coverage test, because name-existence is provably not enough.

No database. There is no Postgres in this suite and there is not going to be one -- a test that
needs a running server is a test that stops being run, and every other migration in this repo is
checked by reading it. These tests are hermetic: no network, no fixture files, no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO / "market_sentiment_tool/supabase/migrations"
ORIGINAL = MIGRATIONS / "20260415090000_signal_events_unification.sql"
FOLLOW_UP = MIGRATIONS / "20260428000013_signal_events_publication_and_rls.sql"

# PostgreSQL's own list of PL/pgSQL condition names, transcribed from
# src/backend/utils/errcodes.txt (the file the server generates plerrcodes.h from, and therefore the
# exact set a `WHEN <name>` clause accepts). One `name sqlstate` pair per line.
#
# The pairs matter as much as the names: a test can only reason about which errors a guard swallows
# if it can turn a condition name back into a SQLSTATE, and it can only do that with the real table
# rather than a hand-kept shortlist that drifts.
_CONDITIONS_TEXT = """
active_sql_transaction 25001
admin_shutdown 57P01
ambiguous_alias 42P09
ambiguous_column 42702
ambiguous_function 42725
ambiguous_parameter 42P08
array_subscript_error 2202E
assert_failure P0004
bad_copy_file_format 22P04
branch_transaction_already_active 25002
cannot_coerce 42846
cannot_connect_now 57P03
cant_change_runtime_param 55P02
cardinality_violation 21000
case_not_found 20000
character_not_in_repertoire 22021
check_violation 23514
collation_mismatch 42P21
config_file_error F0000
configuration_limit_exceeded 53400
connection_does_not_exist 08003
connection_exception 08000
connection_failure 08006
containing_sql_not_permitted 38001
crash_shutdown 57P02
data_corrupted XX001
data_exception 22000
database_dropped 57P04
datatype_mismatch 42804
datetime_field_overflow 22008
deadlock_detected 40P01
dependent_objects_still_exist 2BP01
dependent_privilege_descriptors_still_exist 2B000
deprecated_feature 01P01
diagnostics_exception 0Z000
disk_full 53100
division_by_zero 22012
duplicate_alias 42712
duplicate_column 42701
duplicate_cursor 42P03
duplicate_database 42P04
duplicate_file 58P02
duplicate_function 42723
duplicate_json_object_key_value 22030
duplicate_object 42710
duplicate_prepared_statement 42P05
duplicate_schema 42P06
duplicate_table 42P07
dynamic_result_sets_returned 0100C
error_in_assignment 22005
escape_character_conflict 2200B
event_trigger_protocol_violated 39P03
exclusion_violation 23P01
external_routine_exception 38000
external_routine_invocation_exception 39000
fdw_column_name_not_found HV005
fdw_dynamic_parameter_value_needed HV002
fdw_error HV000
fdw_function_sequence_error HV010
fdw_inconsistent_descriptor_information HV021
fdw_invalid_attribute_value HV024
fdw_invalid_column_name HV007
fdw_invalid_column_number HV008
fdw_invalid_data_type HV004
fdw_invalid_data_type_descriptors HV006
fdw_invalid_descriptor_field_identifier HV091
fdw_invalid_handle HV00B
fdw_invalid_option_index HV00C
fdw_invalid_option_name HV00D
fdw_invalid_string_format HV00A
fdw_invalid_string_length_or_buffer_length HV090
fdw_invalid_use_of_null_pointer HV009
fdw_no_schemas HV00P
fdw_option_name_not_found HV00J
fdw_out_of_memory HV001
fdw_reply_handle HV00K
fdw_schema_not_found HV00Q
fdw_table_not_found HV00R
fdw_too_many_handles HV014
fdw_unable_to_create_execution HV00L
fdw_unable_to_create_reply HV00M
fdw_unable_to_establish_connection HV00N
feature_not_supported 0A000
file_name_too_long 58P03
floating_point_exception 22P01
foreign_key_violation 23503
function_executed_no_return_statement 2F005
generated_always 428C9
grouping_error 42803
held_cursor_requires_same_isolation_level 25008
idle_in_transaction_session_timeout 25P03
idle_session_timeout 57P05
implicit_zero_bit_padding 01008
in_failed_sql_transaction 25P02
inappropriate_access_mode_for_branch_transaction 25003
inappropriate_isolation_level_for_branch_transaction 25004
indeterminate_collation 42P22
indeterminate_datatype 42P18
index_corrupted XX002
indicator_overflow 22022
insufficient_privilege 42501
insufficient_resources 53000
integrity_constraint_violation 23000
internal_error XX000
interval_field_overflow 22015
invalid_argument_for_logarithm 2201E
invalid_argument_for_nth_value_function 22016
invalid_argument_for_ntile_function 22014
invalid_argument_for_power_function 2201F
invalid_argument_for_sql_json_datetime_function 22031
invalid_argument_for_width_bucket_function 2201G
invalid_argument_for_xquery 10608
invalid_authorization_specification 28000
invalid_binary_representation 22P03
invalid_catalog_name 3D000
invalid_character_value_for_cast 22018
invalid_column_definition 42611
invalid_column_reference 42P10
invalid_cursor_definition 42P11
invalid_cursor_name 34000
invalid_cursor_state 24000
invalid_database_definition 42P12
invalid_datetime_format 22007
invalid_escape_character 22019
invalid_escape_octet 2200D
invalid_escape_sequence 22025
invalid_foreign_key 42830
invalid_function_definition 42P13
invalid_grant_operation 0LP01
invalid_grantor 0L000
invalid_indicator_parameter_value 22010
invalid_json_text 22032
invalid_locator_specification 0F001
invalid_name 42602
invalid_object_definition 42P17
invalid_parameter_value 22023
invalid_password 28P01
invalid_preceding_or_following_size 22013
invalid_prepared_statement_definition 42P14
invalid_recursion 42P19
invalid_regular_expression 2201B
invalid_role_specification 0P000
invalid_row_count_in_limit_clause 2201W
invalid_row_count_in_result_offset_clause 2201X
invalid_savepoint_specification 3B001
invalid_schema_definition 42P15
invalid_schema_name 3F000
invalid_sql_json_subscript 22033
invalid_sql_statement_name 26000
invalid_sqlstate_returned 39001
invalid_table_definition 42P16
invalid_tablesample_argument 2202H
invalid_tablesample_repeat 2202G
invalid_text_representation 22P02
invalid_time_zone_displacement_value 22009
invalid_transaction_initiation 0B000
invalid_transaction_state 25000
invalid_transaction_termination 2D000
invalid_use_of_escape_character 2200C
invalid_xml_comment 2200S
invalid_xml_content 2200N
invalid_xml_document 2200M
invalid_xml_processing_instruction 2200T
io_error 58030
locator_exception 0F000
lock_file_exists F0001
lock_not_available 55P03
modifying_sql_data_not_permitted 2F002
more_than_one_sql_json_item 22034
most_specific_type_mismatch 2200G
name_too_long 42622
no_active_sql_transaction 25P01
no_active_sql_transaction_for_branch_transaction 25005
no_additional_dynamic_result_sets_returned 02001
no_data 02000
no_data_found P0002
no_sql_json_item 22035
non_numeric_sql_json_item 22036
non_unique_keys_in_a_json_object 22037
nonstandard_use_of_escape_character 22P06
not_an_xml_document 2200L
not_null_violation 23502
null_value_eliminated_in_set_function 01003
null_value_no_indicator_parameter 22002
null_value_not_allowed 22004
numeric_value_out_of_range 22003
object_in_use 55006
object_not_in_prerequisite_state 55000
operator_intervention 57000
out_of_memory 53200
plpgsql_error P0000
privilege_not_granted 01007
privilege_not_revoked 01006
program_limit_exceeded 54000
prohibited_sql_statement_attempted 2F003
protocol_violation 08P01
query_canceled 57014
raise_exception P0001
read_only_sql_transaction 25006
reading_sql_data_not_permitted 2F004
reserved_name 42939
restrict_violation 23001
savepoint_exception 3B000
schema_and_data_statement_mixing_not_supported 25007
sequence_generator_limit_exceeded 2200H
serialization_failure 40001
singleton_sql_json_item_required 22038
sql_json_array_not_found 22039
sql_json_item_cannot_be_cast_to_target_type 2203G
sql_json_member_not_found 2203A
sql_json_number_not_found 2203B
sql_json_object_not_found 2203C
sql_json_scalar_required 2203F
sql_routine_exception 2F000
sql_statement_not_yet_complete 03000
sqlclient_unable_to_establish_sqlconnection 08001
sqlserver_rejected_establishment_of_sqlconnection 08004
srf_protocol_violated 39P02
stacked_diagnostics_accessed_without_active_handler 0Z002
statement_completion_unknown 40003
statement_too_complex 54001
string_data_length_mismatch 22026
string_data_right_truncation 01004
substring_error 22011
successful_completion 00000
syntax_error 42601
syntax_error_or_access_rule_violation 42000
system_error 58000
too_many_arguments 54023
too_many_columns 54011
too_many_connections 53300
too_many_json_array_elements 2203D
too_many_json_object_members 2203E
too_many_rows P0003
transaction_integrity_constraint_violation 40002
transaction_resolution_unknown 08007
transaction_rollback 40000
transaction_timeout 25P04
trigger_protocol_violated 39P01
triggered_action_exception 09000
triggered_data_change_violation 27000
trim_error 22027
undefined_column 42703
undefined_file 58P01
undefined_function 42883
undefined_object 42704
undefined_parameter 42P02
undefined_table 42P01
unique_violation 23505
unsafe_new_enum_value_usage 55P04
unterminated_c_string 22024
untranslatable_character 22P05
warning 01000
windowing_error 42P20
with_check_option_violation 44000
wrong_object_type 42809
zero_length_character_string 2200F
"""

CONDITION_SQLSTATE: dict[str, str] = {
    parts[0]: parts[1]
    for parts in (line.split() for line in _CONDITIONS_TEXT.splitlines())
    if len(parts) == 2
}


# ── Reading the migrations ─────────────────────────────────────────────────────────────────────


def _strip_comments(sql: str) -> str:
    """SQL with `--` comments removed.

    Both migrations explain the wrong condition names in prose, and `WHEN undefined_table THEN NULL;`
    appears in those comments as well as in the guards. A test that read comments would count the
    prose as a fourth guard and pass for the wrong reason.
    """
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS.glob("*.sql") if p.is_file())


def _exception_guards(sql: str) -> list[tuple[str, list[str], int]]:
    """Every `EXCEPTION` clause in comment-stripped SQL, as (statement, condition names, offset).

    `sql` must already be comment-stripped, and every offset returned is an offset into that same
    string, so "what came before this guard" is answerable without a second parse. `WHEN x OR y THEN`
    and multi-clause `WHEN x THEN ... WHEN y THEN ...` both come back as one flat name list, because
    the thing under test is the set of SQLSTATEs swallowed, not the shape of the clause.
    """
    guards: list[tuple[str, list[str], int]] = []
    # `\s*` before WHEN is not enough. The clauses sit on the lines AFTER `EXCEPTION`, and each
    # clause's own body -- `NULL;` here, but arbitrary PL/pgSQL in general -- sits between one WHEN
    # and the next, so a clause-at-a-time walk from the keyword stops after the FIRST condition. A
    # test that reads one condition out of a three-condition guard and calls it the guard passes on
    # exactly the bug it was written for. So: take the whole clause at once, from EXCEPTION to the
    # end of the dollar-quoted body it lives in.
    clause = re.compile(r"\bWHEN\s+((?:\w+\s+OR\s+)*\w+)\s+THEN\b")
    for match in re.finditer(r"\bEXCEPTION\b", sql):
        close = sql.find("$$", match.end())
        limit = close if close != -1 else len(sql)
        names = [
            part.strip().lower()
            for found in clause.finditer(sql, match.end(), limit)
            for part in re.split(r"\s+OR\s+", found.group(1))
        ]
        if not names:
            continue
        if re.search(r"\bEXCEPTION\b", sql[match.end() : limit], re.I):
            raise AssertionError(
                "two EXCEPTION clauses in one dollar-quoted body; this parser merges them and would "
                "report a union of conditions as each one"
            )
        # The guarded statement is whatever the innermost BEGIN before this EXCEPTION opened. In
        # the `DO $$ BEGIN BEGIN <stmt>; EXCEPTION ...` idiom used throughout these migrations that
        # is the last BEGIN, and the statement is what lies between it and the EXCEPTION keyword.
        before = sql[: match.start()]
        begin = before.rfind("BEGIN")
        statement = (sql[begin + len("BEGIN") : match.start()] if begin != -1 else before).strip()
        guards.append((" ".join(statement.split()), names, match.start()))
    return guards


def _all_guards() -> list[tuple[Path, str, list[str], int]]:
    """Every guard in every migration, with the file it came from."""
    found: list[tuple[Path, str, list[str], int]] = []
    for path in _migration_files():
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for statement, names, offset in _exception_guards(sql):
            found.append((path, statement, names, offset))
    return found


# ── The names ──────────────────────────────────────────────────────────────────────────────────


def test_the_condition_table_is_the_real_one():
    """Guards the guard-guard. A trimmed or typo'd table would make the coverage test meaningless.

    These four are the ones this repository's bugs turn on: 42P01 is a missing relation and
    `undefined_table` is the only name that catches it, 42704 is a missing object of some other kind
    and `undefined_object` is the only name that catches it. Getting either pair backwards or
    collapsing them into one entry is the bug, so the table is asserted rather than trusted.
    """
    for name, sqlstate in (
        ("undefined_table", "42P01"),
        ("undefined_object", "42704"),
        ("duplicate_object", "42710"),
        ("invalid_parameter_value", "22023"),
    ):
        assert CONDITION_SQLSTATE.get(name) == sqlstate, f"{name} should be {sqlstate}"
    assert CONDITION_SQLSTATE["duplicate_table"] == "42P07"
    assert CONDITION_SQLSTATE["unique_violation"] == "23505"
    # A name that does not exist must not be in here, or the existence test below is theatre.
    assert "undefinedobject" not in CONDITION_SQLSTATE
    assert "undefined_relation" not in CONDITION_SQLSTATE
    for name in CONDITION_SQLSTATE:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_every_when_clause_names_a_condition_plpgsql_actually_has():
    """A `WHEN` name outside PostgreSQL's list is a runtime error, not a silent no-op."""
    unknown: list[str] = []
    for path, statement, names, _ in _all_guards():
        for name in names:
            if name not in CONDITION_SQLSTATE:
                unknown.append(f"{path.name}: WHEN {name} (guarding `{statement[:60]}`)")
    assert not unknown, "not PL/pgSQL condition names:\n" + "\n".join(unknown)


def test_the_parser_actually_finds_the_guards():
    """Anti-vacuity. A regex that stops matching makes every test above pass by finding nothing."""
    found = _all_guards()
    assert len(found) >= 4, f"only {len(found)} EXCEPTION guards found; the parser has stopped matching"
    # And the ones it found are the ones a reader would point at, by file.
    found_in = {path.name for path, _, _, _ in found}
    assert "20260415090000_signal_events_unification.sql" in found_in
    assert "20260428000013_signal_events_publication_and_rls.sql" in found_in


# ── The coverage, which is the part that catches this bug ──────────────────────────────────────

# Relations this migration creates for itself, by which a guard knows the relation exists and does
# not need to handle 42P01. `CREATE TABLE` obviously; the rename matters just as much, because a
# rename establishes the new name exactly as firmly as a create does.
_ESTABLISHES = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)"
    r"|\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\w+\s+RENAME\s+TO\s+(\w+)"
    r"|\bCREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)",
    re.IGNORECASE,
)


def _established_before(sql: str, upto: int, relation: str) -> bool:
    """True if this file has already made `relation` exist above offset `upto`."""
    for match in _ESTABLISHES.finditer(sql[:upto]):
        if relation in {g for g in match.groups() if g}:
            return True
    return False


# A follow-up migration creates nothing; it continues a file that already ran. So there is a second
# way for a relation to be known present, and it is the stronger of the two: the same file asserts
# it and checks the assertion before the guard runs. `to_regclass('t') IS NULL THEN RAISE` is that
# check; `tablename = 't'` inside an `IF [NOT] EXISTS (... pg_publication_tables ...)` is the same
# idea for a publication change, where membership is the thing being decided.
_ASSERTS_PRESENT = re.compile(r"""to_regclass\(\s*['"](?P<q>\w+)['"]\s*\)\s+IS\s+NULL""", re.I)
_ASSERTS_MEMBERSHIP = re.compile(r"""tablename\s*=\s*['"](?P<m>\w+)['"]""", re.I)


def _block_start(sql: str, offset: int) -> int:
    """Where the `DO $$` body containing `offset` begins."""
    return sql.rfind("DO $$", 0, offset)


def _assumed_present(sql: str, upto: int, relation: str) -> bool:
    """True if this file has asserted, above `upto`, that `relation` is there.

    Two assertions count, and the scoping differs on purpose.

    - `to_regclass('t') IS NULL THEN RAISE EXCEPTION` is a file-level precondition, checked once
      near the top and holding for everything below it, so it is searched for anywhere above.
    - `tablename = 't'` inside the guard's own `DO $$` body is scoped to that body. Scoping it
      file-wide would be wrong: the ADD block would read the DROP block's membership test and vice
      versa, and each would stop being required to handle a relation that is genuinely absent. It
      is also correct to honour it -- you cannot be a member of a publication unless you exist.
    """
    if any(m.group(1) == relation for m in _ASSERTS_PRESENT.finditer(sql[:upto])):
        return True
    body = sql[_block_start(sql, upto) : upto]
    return any(m.group(1) == relation for m in _ASSERTS_MEMBERSHIP.finditer(body))


def _relations_named(statement: str) -> set[str]:
    """Relation names a statement refers to by name, for `ALTER PUBLICATION` statements.

    Publication membership is the only guarded DDL in these migrations that names a relation without
    also being able to create it, so this stays narrow on purpose: a wider rule would start making
    demands about statements nothing here writes.
    """
    found: set[str] = set()
    pub = re.search(r"ALTER\s+PUBLICATION\s+\w+\s+(?:ADD|DROP)\s+TABLE\s+(.+?);?$", statement, re.I | re.S)
    if pub:
        found.update(re.findall(r"\b(\w+)\b", pub.group(1).replace("ONLY", " ")))
    return {name for name in found if name.lower() not in {"if", "exists", "table", "only"}}


def _required_sqlstates(statement: str, sql: str, offset: int) -> set[str]:  # noqa: C901
    """SQLSTATEs `statement` can raise that a guard around it has to swallow.

    Three rules, each from what PostgreSQL does rather than from taste:

    - A relation named in the statement that this file has not already created is 42P01. That is
      the production failure: the rename at line 1 took the old name away, so `crypto_signal_events`
      is not a relation by the time the guard runs. If the file *does* establish the relation
      earlier -- created, or renamed into place -- the error is impossible and must not be
      demanded, which is why `signal_events` is treated differently from `crypto_signal_events` in
      the very next file down. That distinction is the whole test.
    - A file that does not create the relation is not automatically wrong about it either. A
      follow-up migration asserts the relation is present and verifies that assertion in the same
      file; a relation known to be there cannot raise 42P01, and the file says so out loud.
    - `ALTER PUBLICATION ... DROP TABLE` on a relation that exists but is not a member raises 42704,
      not 55000: `PublicationDropTables` is called with missing=false and reports it as
      undefined_object. This is the one condition in the original file that was right all along.
    - `ADD TABLE` raises 42710 when the table is already a member and 42704 when the publication
      itself is missing, so both belong in that guard regardless of anything about relations.
    """
    required: set[str] = set()
    relations = _relations_named(statement)
    if relations:
        for relation in relations:
            if _established_before(sql, offset, relation):
                continue
            if _assumed_present(sql, offset, relation):
                continue
            required.add("42P01")
    if re.search(r"ALTER\s+PUBLICATION\s+\w+\s+DROP\s+TABLE", statement, re.I):
        required.add("42704")
    if re.search(r"ALTER\s+PUBLICATION\s+\w+\s+ADD\s+TABLE", statement, re.I):
        required |= {"42710", "42704"}
    return required


def test_every_exception_guard_covers_the_sqlstates_its_statement_can_raise():
    """The regression test. Put the 42P01 condition back and this fails."""
    problems: list[str] = []
    for path, statement, names, offset in _all_guards():
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        required = _required_sqlstates(statement, sql, offset)
        covered = {CONDITION_SQLSTATE.get(name, "?") for name in names}
        missing = required - covered
        if missing:
            problems.append(
                f"{path.name} over `{statement[:70]}`: swallows {sorted(covered)} but can raise "
                f"{sorted(required)} -- missing {sorted(missing)}"
            )
    assert not problems, "EXCEPTION guards that cannot catch their own statement:\n" + "\n".join(problems)


def test_a_guard_is_never_defined_only_by_undefined_object():
    """`undefined_object` alone is always a hole.

    42704 is undefined function/operator, undefined publication, undefined parameter name -- never a
    missing table, which is 42P01. So a guard whose only condition is `undefined_object` is a guard
    that has decided, in writing, that the table it names always exists. That was true of
    `20260415090000` before this change and false in fact: line 1 had just renamed the table away.
    """
    for path, statement, names, _ in _all_guards():
        if set(names) == {"undefined_object"}:
            raise AssertionError(
                f"{path.name}: `WHEN undefined_object` is the only condition over `{statement[:70]}`. "
                "A missing relation is 42P01/undefined_table, which this cannot catch."
            )


def _original_guards() -> list[tuple[str, list[str]]]:
    sql = _strip_comments(ORIGINAL.read_text(encoding="utf-8"))
    return [(statement, names) for statement, names, _ in _exception_guards(sql)]


def test_the_production_failure_statement_is_now_guarded_for_42p01():
    """Named explicitly so the regression is legible in a diff, not only in a rule."""
    drop = [names for statement, names in _original_guards()
            if "DROP TABLE crypto_signal_events" in statement]
    assert drop, "the publication DROP guard is gone from 20260415090000"
    assert "undefined_table" in drop[0], "42P01 is undefined_table; the guard must name it"
    assert "undefined_object" in drop[0], "42704 (relation not in the publication) is still required"
    assert "invalid_parameter_value" in drop[0]


def test_the_add_publication_guard_keeps_undefined_object():
    """The other `EXCEPTION` block was NOT the same bug, and this stops it being "fixed" into one.

    The object that can be missing from `ALTER PUBLICATION p ADD TABLE t` is the publication, and a
    missing publication is 42704 `undefined_object`. The table cannot be missing, because the
    migration created it or renamed it into place long above. Rewriting that name to
    `undefined_table` would be a second wrong answer to the same review comment.
    """
    add = [names for statement, names in _original_guards() if "ADD TABLE signal_events" in statement]
    assert add, "the publication ADD guard is gone from 20260415090000"
    assert "duplicate_object" in add[0], "42710: already a member"
    assert "undefined_object" in add[0], "42704: the publication is missing"
    assert "undefined_table" not in add[0], (
        "42P01 cannot occur here -- signal_events is created or renamed into place above this block. "
        "Adding undefined_table would be noise, and dropping undefined_object would break the "
        "missing-publication case."
    )


def test_no_migration_guards_a_rename_with_a_bare_begin():
    """`ALTER TABLE ... RENAME` has no IF EXISTS form that suppresses a missing source table."""
    for path, statement, _names, _offset in _all_guards():
        if re.search(r"RENAME\s+TO", statement, re.I):
            raise AssertionError(f"{path.name}: `{statement[:80]}` is guarded as if it were safe")


# ── The follow-up migration ────────────────────────────────────────────────────────────────────


def _split_statements(sql: str) -> list[str]:
    """Split on top-level semicolons, ignoring semicolons inside `$$ ... $$` bodies.

    The trigger functions are single statements whose bodies are full of semicolons, so a naive
    split produces fragments that match nothing.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(sql):
        if sql.startswith("$$", i):
            end = sql.find("$$", i + 2)
            end = len(sql) if end == -1 else end + 2
            current.append(sql[i:end])
            i = end
            continue
        if sql[i] == ";":
            statements.append("".join(current))
            current = []
            i += 1
            continue
        current.append(sql[i])
        i += 1
    if "".join(current).strip():
        statements.append("".join(current))
    return [" ".join(s.split()) for s in statements if s.strip()]


def _tail_of_original() -> list[str]:
    """The statements of 20260415090000 from the failing block onward.

    Cut at the second DO block, which is exactly where the original stopped: the failing block is
    the first one and everything from the second onward never ran in production.
    """
    sql = _strip_comments(ORIGINAL.read_text(encoding="utf-8"))
    second_do = sql.index("DO $$", sql.index("DO $$") + 1)
    return _split_statements(sql[second_do:])


def _objects_touched(sql: str) -> set[str]:
    """Every relation/policy/trigger name a script creates, drops or RLS-enables.

    Compared as a set of names rather than as statement text, because the follow-up is allowed to
    add a membership check around a publication change and a couple of extra DROP POLICY lines; what
    it is not allowed to do is quietly leave an object behind.
    """
    sql = _strip_comments(sql)
    names: set[str] = set()
    for match in re.finditer(
        r"\b(?:CREATE\s+(?:OR\s+REPLACE\s+)?|DROP\s+)(?:TABLE|VIEW|FUNCTION|TRIGGER|POLICY)\s+"
        r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:\"([^\"]+)\"|(?:(\w+)\.)?(\w+))",
        sql,
        re.I,
    ):
        # Policy names are quoted and contain spaces; the rest may be schema-qualified.
        names.add((match.group(1) or match.group(3)).lower())
    for match in re.finditer(r"\bALTER\s+TABLE\s+(\w+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql, re.I):
        names.add(match.group(1).lower())
    for match in re.finditer(r"ALTER\s+PUBLICATION\s+\w+\s+ADD\s+TABLE\s+(\w+)", sql, re.I):
        names.add(match.group(1).lower())
    return names


def test_the_follow_up_exists_and_is_numbered_after_what_it_completes():
    """It must apply after the migration it finishes. Later migrations (the journal's 000014 and
    onward) may sort after it; "newest file in the folder" was never the requirement, and asserting
    it would have failed the moment any migration was added."""
    assert FOLLOW_UP.is_file(), f"{FOLLOW_UP.name} is missing"
    earlier = [p for p in _migration_files() if p.name < FOLLOW_UP.name]
    assert ORIGINAL in earlier, f"{FOLLOW_UP.name} must sort after {ORIGINAL.name}; migrations apply in name order"
    clashes = [p.name for p in _migration_files() if p != FOLLOW_UP and p.name[:14] == FOLLOW_UP.name[:14]]
    assert not clashes, f"another migration shares {FOLLOW_UP.name[:14]}: {clashes}"
    assert FOLLOW_UP.name.endswith("_signal_events_publication_and_rls.sql")
    assert "20260428000013" in FOLLOW_UP.name


def test_the_follow_up_does_every_statement_the_original_never_reached():
    """The whole point of the file: line 58 onward, object for object."""
    wanted = _objects_touched("\n".join(_tail_of_original()))
    assert wanted, "the tail of 20260415090000 parsed to nothing; the test would pass for free"
    done = _objects_touched(FOLLOW_UP.read_text(encoding="utf-8"))
    missing = wanted - done
    assert not missing, f"the follow-up leaves these untouched: {sorted(missing)}"
    # Spelled out, because "a set difference came back empty" is not something a reader can check.
    for expected in (
        "signal_events",
        "crypto_signal_events",
        "crypto_signal_events_insert",
        "crypto_signal_events_update",
        "crypto_signal_events_delete",
        "crypto_signal_events_insert_trigger",
        "crypto_signal_events_update_trigger",
        "crypto_signal_events_delete_trigger",
        'users can view their own signal events',
        'anon can view signal events',
    ):
        assert expected in done, expected


def _without_publication_statements(sql: str) -> str:
    """`sql` with every `ALTER PUBLICATION ...;` removed.

    Needed because `ALTER PUBLICATION supabase_realtime DROP TABLE x` contains the words DROP TABLE
    and is about publication membership, not about destroying a relation. Scanning for destructive
    DDL without this first produces a false positive on the one statement the file must contain.
    """
    return re.sub(r"ALTER\s+PUBLICATION\b[^;]*;", "", sql, flags=re.I)


def test_the_follow_up_is_idempotent():
    """Every statement has to survive running it twice, which is how it will actually be applied."""
    sql = FOLLOW_UP.read_text(encoding="utf-8")
    body = _strip_comments(sql)
    collapsed = " ".join(body.split())

    for pattern, why in (
        (r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", "a bare CREATE TABLE fails on a re-run"),
        (r"CREATE\s+VIEW\s+(?!OR\s+REPLACE)", "a bare CREATE VIEW fails on a re-run"),
        (r"CREATE\s+FUNCTION\s+(?!.*OR\s+REPLACE)", "a bare CREATE FUNCTION fails on a re-run"),
    ):
        offenders = re.findall(pattern, collapsed, re.I)
        assert not offenders, f"{why}: {offenders[:3]}"

    for match in re.finditer(r"CREATE\s+POLICY\s+\"?([\w ]+)\"?", collapsed, re.I):
        name = match.group(1)
        assert f'DROP POLICY IF EXISTS "{name}"' in collapsed[: match.start()], (
            f'policy "{name}" is created without a DROP POLICY IF EXISTS above it'
        )

    for match in re.finditer(r"CREATE\s+TRIGGER\s+(\w+)", collapsed, re.I):
        name = match.group(1)
        assert f"DROP TRIGGER IF EXISTS {name}" in collapsed[: match.start()], (
            f"trigger {name} is created without a DROP TRIGGER IF EXISTS above it"
        )

    # A publication change guarded only by catching the error is a guard with a wrong condition name
    # waiting to happen, so the follow-up decides membership by looking before it acts.
    assert "pg_publication_tables" in body, (
        "publication membership must be tested with pg_publication_tables, not inferred from a "
        "caught error code"
    )
    # The DO-block guard opens above the statement and closes below it, so the window has to look
    # both ways; a purely backwards search finds the membership check and not the EXCEPTION.
    for match in re.finditer(r"ALTER\s+PUBLICATION[^;]*;", body, re.I):
        around = body[max(0, match.start() - 1200) : match.end() + 1200]
        assert re.search(r"EXCEPTION\s+WHEN\s+\w+", around, re.I), (
            f"unguarded publication change: {match.group(0)[:80]}"
        )
        assert re.search(r"pg_publication_tables", around, re.I), (
            f"publication change not decided by membership: {match.group(0)[:80]}"
        )


def test_the_follow_up_never_destroys_the_signal_ledger():
    """`signal_events` is the production signal ledger; every writer writes to it with the service
    role and the shadow scorer reads it. A follow-up that drops or truncates it to 'start clean'
    deletes real history, which is the one thing a repair like this must never do."""
    body = _without_publication_statements(_strip_comments(FOLLOW_UP.read_text(encoding="utf-8")))
    for pattern in (
        r"\bDROP\s+TABLE\s+(?!IF\s+EXISTS)",
        r"\bTRUNCATE\b",
        r"\bDROP\s+SCHEMA\b",
        r"\bDELETE\s+FROM\s+signal_events\b",
    ):
        offenders = re.findall(pattern, body, re.I)
        assert not offenders, f"{pattern} in the follow-up would destroy data: {offenders[:3]}"
    # The ledger is also what makes the follow-up better than a reset, so say so in the file.
    assert "does not drop" in FOLLOW_UP.read_text(encoding="utf-8").lower() or "NOT a reset" in (
        FOLLOW_UP.read_text(encoding="utf-8")
    )


def test_the_follow_up_states_and_checks_its_precondition():
    """Requirement 3: the owner has to be able to run this with confidence.

    The single assumption is that `signal_events` exists, and the file has to say so in words AND
    verify it, because a migration that assumes the wrong starting state is a second broken
    migration. The check has to be a hard failure: silently creating the policies against nothing
    is the failure mode.
    """
    sql = FOLLOW_UP.read_text(encoding="utf-8")
    assert "ASSUMED ALREADY APPLIED" in sql
    assert "to_regclass('signal_events')" in sql, "the assumption is stated but not checked"
    assert re.search(r"RAISE\s+EXCEPTION", sql), "the precondition check must fail loudly"
    assert "20260415090000" in sql, "the error must name the file that has to be applied first"


def test_the_assumed_precondition_is_provable_from_this_repo():
    """Not a guess. The table is established at or before the follow-up, so the assumption holds for
    a fresh database and for the half-applied production one alike."""
    establishing = [
        path
        for path in _migration_files()
        if path != FOLLOW_UP
        and any(
            match.groups() and "signal_events" in {g for g in match.groups() if g}
            for match in _ESTABLISHES.finditer(_strip_comments(path.read_text(encoding="utf-8")))
        )
    ]
    assert establishing, "no migration creates or renames signal_events; the precondition is unsound"
    assert max(establishing) < FOLLOW_UP, (
        f"signal_events is established by {[p.name for p in establishing]}, which sorts after the "
        "follow-up and so cannot be assumed"
    )
    assert "ALTER TABLE IF EXISTS crypto_signal_events RENAME TO signal_events" in (
        ORIGINAL.read_text(encoding="utf-8")
    ), "the rename is the owner's applied statement; it must stay in the original, not move"


def test_the_follow_up_does_not_repeat_the_rename():
    """Only one file may own the rename, or a fresh database gets two stories about one table."""
    assert not re.search(r"RENAME\s+TO\s+signal_events", FOLLOW_UP.read_text(encoding="utf-8"))
