#!/bin/bash
set -eu
# Passwords are generated hex by prepare-source-lab.ps1. Never print this input.
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -u root lab <<SQL
CREATE TABLE operations (id integer PRIMARY KEY, batch varchar(32), amount decimal(20,4), recipient varchar(100), active boolean, unsupported json);
INSERT INTO operations VALUES (1,'duplicate',11500.1250,'Учебный получатель',true,'{}'),(2,'duplicate',4500.0000,'Другой получатель',false,'{}'),(3,'empty',NULL,NULL,NULL,NULL);
CREATE USER 'lab_reader'@'%' IDENTIFIED BY '$SOURCE_LAB_READER_PASSWORD';
GRANT SELECT ON lab.operations TO 'lab_reader'@'%';
CREATE USER 'lab_denied'@'%' IDENTIFIED BY '$SOURCE_LAB_READER_PASSWORD';
CREATE USER 'lab_writer'@'%' IDENTIFIED BY '$SOURCE_LAB_READER_PASSWORD';
GRANT SELECT, INSERT ON lab.operations TO 'lab_writer'@'%';
SQL
