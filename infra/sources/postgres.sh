#!/bin/bash
set -eu
psql -v ON_ERROR_STOP=1 -U postgres -d lab -v reader_password="$SOURCE_LAB_READER_PASSWORD" <<'SQL'
CREATE TABLE public.operations (id integer PRIMARY KEY, batch varchar(32), amount numeric(20,4), recipient text, active boolean, unsupported jsonb);
INSERT INTO public.operations VALUES (1,'duplicate',11500.1250,'Учебный получатель',true,'{}'),(2,'duplicate',4500.0000,'Другой получатель',false,'{}'),(3,'empty',NULL,NULL,NULL,NULL);
CREATE ROLE lab_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE lab TO lab_reader;
GRANT USAGE ON SCHEMA public TO lab_reader;
GRANT SELECT ON public.operations TO lab_reader;
CREATE ROLE lab_denied LOGIN PASSWORD :'reader_password';
CREATE ROLE lab_writer LOGIN PASSWORD :'reader_password';
GRANT SELECT, INSERT ON public.operations TO lab_writer;
SQL
