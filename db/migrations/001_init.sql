-- Pack Manager schema. Run by `python -m app.migrate` with the admin connection.
--
-- Tenancy (engineering rule 1): every tenant table has row-level security ENABLED and
-- FORCED. Policies compare organization_id with the transaction-local setting app.org_id,
-- which the app sets at the start of every transaction. With no setting, no rows match.
-- The app connects as pack_app: not the owner, not a superuser, no BYPASSRLS.

create table if not exists organizations (
    id   text primary key,
    name text not null
);

create table if not exists access_codes (
    code_hash       text primary key,          -- sha256 of the access code
    organization_id text not null references organizations(id),
    operator_label  text not null
);

create table if not exists orders (
    organization_id text not null references organizations(id),
    order_id        text not null,
    client_id       text,
    unit_id         text,
    channel         text,
    lines           jsonb not null,
    source          text not null default 'demo',
    created_at      timestamptz not null default now(),
    primary key (organization_id, order_id)
);
-- Evidence Contract 1.1: subject.shipment_id. Added after the first deploy, so it's added here
-- rather than in the create table above.
alter table orders add column if not exists shipment_id text;

create table if not exists records (
    record_id       text primary key,
    organization_id text not null references organizations(id),
    order_id        text,
    unit_id         text,
    decision        text not null,
    status          text not null,
    captured_at     timestamptz not null,
    content_hash    text not null,
    record          jsonb not null,
    updated_at      timestamptz not null default now()
);
create index if not exists records_org_order on records (organization_id, order_id);
create index if not exists records_org_unit on records (organization_id, unit_id);
-- Finding the AI re-check of a record, so a retried record leaves the "needs a decision" queue.
create index if not exists records_retry_of on records ((record->'observations'->>'retry_of'));

-- Photos live in the database under the same policy as records, and are addressed by a
-- random UUID. There is no file path to guess, and a guessed UUID from another tenant
-- still returns nothing.
create table if not exists images (
    image_id        uuid primary key,
    organization_id text not null references organizations(id),
    record_id       text not null references records(record_id),
    sha256          text not null,
    mime            text not null,
    content         bytea not null,
    created_at      timestamptz not null default now()
);

-- Finding a reused photo (same bytes uploaded for another order).
create index if not exists images_org_sha on images (organization_id, sha256);

do $$
declare t text;
begin
    foreach t in array array['organizations', 'orders', 'records', 'images'] loop
        execute format('alter table %I enable row level security', t);
        execute format('alter table %I force row level security', t);
    end loop;
end $$;

drop policy if exists tenant_isolation on organizations;
create policy tenant_isolation on organizations
    using (id = current_setting('app.org_id', true));

drop policy if exists tenant_isolation on orders;
create policy tenant_isolation on orders
    using (organization_id = current_setting('app.org_id', true))
    with check (organization_id = current_setting('app.org_id', true));

drop policy if exists tenant_isolation on records;
create policy tenant_isolation on records
    using (organization_id = current_setting('app.org_id', true))
    with check (organization_id = current_setting('app.org_id', true));

drop policy if exists tenant_isolation on images;
create policy tenant_isolation on images
    using (organization_id = current_setting('app.org_id', true))
    with check (organization_id = current_setting('app.org_id', true));

-- Access codes are never readable by the app role. Sign-in goes through this function,
-- which returns only the one matching row.
alter table access_codes enable row level security;

create or replace function resolve_access_code(p_code_hash text)
returns table (organization_id text, operator_label text)
language sql
security definer
set search_path = public, pg_temp
as $$
    select organization_id, operator_label from access_codes where code_hash = p_code_hash
$$;

-- Evidence only grows (overrides are data). An update may add hand decisions at the end and
-- change the outcome, status and hash with them. Everything the agent saved, and every earlier
-- decision, must stay exactly as it was. The database enforces this for every role, the app's
-- included, so a bug or a stolen app password can't quietly rewrite a record's history.
create or replace function records_append_only() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
    old_n int := coalesce(jsonb_array_length(old.record->'overrides'), 0);
    new_n int := coalesce(jsonb_array_length(new.record->'overrides'), 0);
    mutable text[] := array['outcome', 'status', 'overrides', 'content_hash'];
begin
    if new.record_id <> old.record_id or new.organization_id <> old.organization_id
       or new.captured_at <> old.captured_at then
        raise exception 'records are append-only: % keeps its id, organisation and time', old.record_id;
    end if;
    if (new.record - mutable) is distinct from (old.record - mutable) then
        raise exception 'records are append-only: the agent''s part of % can''t change', old.record_id;
    end if;
    if new_n <= old_n then
        raise exception 'records are append-only: a change to % must add a decision', old.record_id;
    end if;
    for i in 0 .. old_n - 1 loop
        if (new.record->'overrides'->i) is distinct from (old.record->'overrides'->i) then
            raise exception 'records are append-only: earlier decisions on % can''t change', old.record_id;
        end if;
    end loop;
    return new;
end $$;

drop trigger if exists records_append_only on records;
create trigger records_append_only before update on records
    for each row execute function records_append_only();
