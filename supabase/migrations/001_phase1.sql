-- VALLIÈRE — Fase 1
-- Execute no SQL Editor de um projeto Supabase privado.

create table if not exists public.world_states (
  guild_id bigint primary key,
  narrative_day integer not null default 1 check (narrative_day >= 1),
  day_label text not null default 'SEGUNDA-FEIRA',
  period text not null check (period in ('MANHÃ', 'TARDE', 'NOITE', 'MADRUGADA')),
  city_status text not null check (city_status in ('ATIVA', 'DORMINDO')),
  weather text not null default 'céu parcialmente nublado',
  updated_at timestamptz not null default now()
);

create table if not exists public.locations (
  guild_id bigint not null,
  channel_id bigint not null,
  category_id bigint,
  category_name text not null,
  channel_name text not null,
  kind text not null check (kind in ('FISICO', 'DIGITAL', 'ADMINISTRATIVO')),
  building text,
  room text,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (guild_id, channel_id)
);

create table if not exists public.characters (
  character_id text primary key,
  display_name text not null,
  actor_kind text not null check (actor_kind in ('HUMANO', 'IA')),
  controller_discord_user_id bigint,
  avatar_url text,
  residence_location_key text,
  current_location_key text,
  activity text not null default 'indefinida',
  profile jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- O bot usa exclusivamente a service role no servidor. Nenhuma tabela fica
-- disponível diretamente para usuários anônimos ou autenticados do Supabase.
alter table public.world_states enable row level security;
alter table public.locations enable row level security;
alter table public.characters enable row level security;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists world_states_updated_at on public.world_states;
create trigger world_states_updated_at before update on public.world_states
for each row execute function public.set_updated_at();

drop trigger if exists locations_updated_at on public.locations;
create trigger locations_updated_at before update on public.locations
for each row execute function public.set_updated_at();

drop trigger if exists characters_updated_at on public.characters;
create trigger characters_updated_at before update on public.characters
for each row execute function public.set_updated_at();
