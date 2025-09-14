BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> df0bbc52c089

CREATE TABLE expense_categories (
    id SERIAL NOT NULL, 
    name VARCHAR NOT NULL, 
    icon VARCHAR, 
    PRIMARY KEY (id)
);

COMMENT ON COLUMN expense_categories.name IS 'Название категории (например, ''Еда'')';

COMMENT ON COLUMN expense_categories.icon IS 'Иконка или emoji категории (например, ''🍕'' или ''food'')';

CREATE INDEX ix_expense_categories_id ON expense_categories (id);

CREATE TABLE users (
    id SERIAL NOT NULL, 
    telegram_id INTEGER NOT NULL, 
    username VARCHAR, 
    first_name VARCHAR, 
    last_name VARCHAR, 
    name VARCHAR, 
    photo_url VARCHAR, 
    language_code VARCHAR(8), 
    allows_write_to_pm BOOLEAN, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_users_id ON users (id);

CREATE INDEX ix_users_name ON users (name);

CREATE UNIQUE INDEX ix_users_telegram_id ON users (telegram_id);

CREATE INDEX ix_users_username ON users (username);

CREATE TABLE friends (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    friend_id INTEGER NOT NULL, 
    status VARCHAR NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(friend_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT _user_friend_uc UNIQUE (user_id, friend_id)
);

CREATE INDEX ix_friends_id ON friends (id);

CREATE TABLE groups (
    id SERIAL NOT NULL, 
    name VARCHAR, 
    description VARCHAR, 
    owner_id INTEGER, 
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE INDEX ix_groups_id ON groups (id);

CREATE INDEX ix_groups_name ON groups (name);

CREATE TABLE group_members (
    id SERIAL NOT NULL, 
    group_id INTEGER, 
    user_id INTEGER, 
    PRIMARY KEY (id), 
    FOREIGN KEY(group_id) REFERENCES groups (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_group_members_id ON group_members (id);

CREATE TABLE transactions (
    id SERIAL NOT NULL, 
    group_id INTEGER NOT NULL, 
    created_by INTEGER NOT NULL, 
    type VARCHAR NOT NULL, 
    amount FLOAT NOT NULL, 
    date TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    comment VARCHAR, 
    category_id INTEGER, 
    paid_by INTEGER, 
    split_type VARCHAR, 
    transfer_from INTEGER, 
    transfer_to JSON, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    currency VARCHAR, 
    is_deleted BOOLEAN, 
    receipt_url VARCHAR, 
    receipt_data JSON, 
    PRIMARY KEY (id), 
    FOREIGN KEY(category_id) REFERENCES expense_categories (id), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    FOREIGN KEY(group_id) REFERENCES groups (id), 
    FOREIGN KEY(paid_by) REFERENCES users (id), 
    FOREIGN KEY(transfer_from) REFERENCES users (id)
);

COMMENT ON COLUMN transactions.group_id IS 'ID группы, к которой относится транзакция';

COMMENT ON COLUMN transactions.created_by IS 'Пользователь, создавший транзакцию';

COMMENT ON COLUMN transactions.type IS '''expense'' — расход, ''transfer'' — перевод (транш)';

COMMENT ON COLUMN transactions.amount IS 'Сумма транзакции';

COMMENT ON COLUMN transactions.date IS 'Дата расхода/транша';

COMMENT ON COLUMN transactions.comment IS 'Комментарий или описание';

COMMENT ON COLUMN transactions.category_id IS 'Категория расхода (только для type=''expense'')';

COMMENT ON COLUMN transactions.paid_by IS 'Кто оплатил (для расходов)';

COMMENT ON COLUMN transactions.split_type IS 'Тип деления (''equal'', ''shares'', ''custom'')';

COMMENT ON COLUMN transactions.transfer_from IS 'Отправитель денег (только для type=''transfer'')';

COMMENT ON COLUMN transactions.transfer_to IS 'Список получателей (user_id), для transfer — один или несколько, JSON-массив';

COMMENT ON COLUMN transactions.created_at IS 'Дата и время создания';

COMMENT ON COLUMN transactions.updated_at IS 'Дата и время последнего изменения';

COMMENT ON COLUMN transactions.currency IS 'Валюта транзакции, по умолчанию RUB';

COMMENT ON COLUMN transactions.is_deleted IS 'Признак soft delete (архивирования)';

COMMENT ON COLUMN transactions.receipt_url IS 'Ссылка на файл чека (если прикреплён)';

COMMENT ON COLUMN transactions.receipt_data IS 'Результат распознавания чека (массив товаров, итог и т.д.)';

CREATE INDEX ix_transactions_id ON transactions (id);

CREATE TABLE transaction_shares (
    id SERIAL NOT NULL, 
    transaction_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    amount FLOAT NOT NULL, 
    shares INTEGER, 
    PRIMARY KEY (id), 
    FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

COMMENT ON COLUMN transaction_shares.transaction_id IS 'ID транзакции';

COMMENT ON COLUMN transaction_shares.user_id IS 'Участник группы';

COMMENT ON COLUMN transaction_shares.amount IS 'Сумма, которую должен этот участник';

COMMENT ON COLUMN transaction_shares.shares IS 'Кол-во долей (если split_type=''shares'')';

CREATE INDEX ix_transaction_shares_id ON transaction_shares (id);

INSERT INTO alembic_version (version_num) VALUES ('df0bbc52c089') RETURNING alembic_version.version_num;

-- Running upgrade df0bbc52c089 -> 6bb6e9e433e7

ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT;

UPDATE alembic_version SET version_num='6bb6e9e433e7' WHERE alembic_version.version_num = 'df0bbc52c089';

-- Running upgrade 6bb6e9e433e7 -> 2cc12f3469b7

ALTER TABLE users ADD COLUMN is_pro BOOLEAN DEFAULT FALSE NOT NULL;

ALTER TABLE users ADD COLUMN invited_friends_count INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE friends DROP COLUMN status;

UPDATE alembic_version SET version_num='2cc12f3469b7' WHERE alembic_version.version_num = '6bb6e9e433e7';

-- Running upgrade 2cc12f3469b7 -> fcab50bc945c

CREATE TABLE friend_invites (
    id SERIAL NOT NULL, 
    from_user_id INTEGER NOT NULL, 
    token VARCHAR NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(from_user_id) REFERENCES users (id)
);

CREATE INDEX ix_friend_invites_id ON friend_invites (id);

CREATE UNIQUE INDEX ix_friend_invites_token ON friend_invites (token);

CREATE TABLE events (
    id SERIAL NOT NULL, 
    actor_id INTEGER NOT NULL, 
    target_user_id INTEGER, 
    group_id INTEGER, 
    type VARCHAR NOT NULL, 
    data JSON, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_id) REFERENCES users (id), 
    FOREIGN KEY(group_id) REFERENCES groups (id), 
    FOREIGN KEY(target_user_id) REFERENCES users (id)
);

CREATE TABLE invite_usages (
    id SERIAL NOT NULL, 
    invite_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    used_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(invite_id) REFERENCES friend_invites (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

ALTER TABLE friends ADD COLUMN hidden BOOLEAN;

ALTER TABLE users ALTER COLUMN is_pro DROP DEFAULT;

COMMENT ON COLUMN users.is_pro IS 'Является ли пользователь PRO';

ALTER TABLE users ALTER COLUMN invited_friends_count DROP DEFAULT;

COMMENT ON COLUMN users.invited_friends_count IS 'Сколько друзей добавлено по инвайт-ссылке';

UPDATE alembic_version SET version_num='fcab50bc945c' WHERE alembic_version.version_num = '2cc12f3469b7';

-- Running upgrade fcab50bc945c -> 7b08661241e1

CREATE TABLE group_invites (
    id SERIAL NOT NULL, 
    group_id INTEGER NOT NULL, 
    token VARCHAR NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(group_id) REFERENCES groups (id)
);

CREATE INDEX ix_group_invites_id ON group_invites (id);

CREATE UNIQUE INDEX ix_group_invites_token ON group_invites (token);

UPDATE alembic_version SET version_num='7b08661241e1' WHERE alembic_version.version_num = 'fcab50bc945c';

-- Running upgrade 7b08661241e1 -> 2025_08_08_groups_v2

CREATE TYPE group_status AS ENUM ('active', 'archived');

ALTER TABLE groups ADD COLUMN status group_status DEFAULT 'active' NOT NULL;

ALTER TABLE groups ADD COLUMN archived_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE groups ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE groups ADD COLUMN end_date DATE;

ALTER TABLE groups ADD COLUMN auto_archive BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE groups ADD COLUMN default_currency_code VARCHAR(3) DEFAULT 'RUB' NOT NULL;

UPDATE groups SET default_currency_code = 'RUB' WHERE default_currency_code IS NULL;;

CREATE TABLE currencies (
    code VARCHAR(3) NOT NULL, 
    numeric_code SMALLINT NOT NULL, 
    decimals SMALLINT NOT NULL, 
    symbol VARCHAR(8), 
    flag_emoji VARCHAR(8), 
    display_country VARCHAR(2), 
    name_i18n JSONB NOT NULL, 
    is_popular BOOLEAN DEFAULT false NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (code)
);

COMMENT ON COLUMN currencies.code IS 'Код валюты ISO-4217, напр. ''USD''';

COMMENT ON COLUMN currencies.numeric_code IS 'Числовой код ISO-4217';

COMMENT ON COLUMN currencies.decimals IS 'Кол-во знаков после запятой';

COMMENT ON COLUMN currencies.symbol IS 'Символ валюты';

COMMENT ON COLUMN currencies.flag_emoji IS 'Эмодзи флага';

COMMENT ON COLUMN currencies.display_country IS 'ISO-3166 код региона для отображения';

COMMENT ON COLUMN currencies.name_i18n IS 'Локализованные названия';

ALTER TABLE currencies ADD CONSTRAINT uq_currencies_numeric_code UNIQUE (numeric_code);

CREATE INDEX ix_currencies_is_popular ON currencies (is_popular);

CREATE INDEX ix_currencies_is_active ON currencies (is_active);

CREATE INDEX ix_currencies_numeric_code ON currencies (numeric_code);

CREATE TABLE group_hidden (
    group_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    hidden_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_group_hidden PRIMARY KEY (group_id, user_id), 
    FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

COMMENT ON COLUMN group_hidden.group_id IS 'ID группы';

COMMENT ON COLUMN group_hidden.user_id IS 'ID пользователя';

CREATE INDEX ix_group_hidden_user_id ON group_hidden (user_id);

CREATE TABLE group_categories (
    group_id INTEGER NOT NULL, 
    category_id INTEGER NOT NULL, 
    created_by INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_group_categories PRIMARY KEY (group_id, category_id), 
    FOREIGN KEY(group_id) REFERENCES groups (id) ON DELETE CASCADE, 
    FOREIGN KEY(category_id) REFERENCES expense_categories (id) ON DELETE CASCADE, 
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_group_categories_group_id ON group_categories (group_id);

CREATE INDEX ix_group_categories_category_id ON group_categories (category_id);

DELETE FROM group_members gm
    USING (
      SELECT id
      FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY group_id, user_id ORDER BY id) AS rn
        FROM group_members
      ) t
      WHERE t.rn > 1
    ) d
    WHERE gm.id = d.id;;

CREATE TEMP TABLE txs_agg AS
    SELECT
      transaction_id,
      user_id,
      COALESCE(SUM(amount), 0) AS amount,
      CASE
        WHEN COUNT(shares) FILTER (WHERE shares IS NOT NULL) = 0 THEN NULL
        ELSE COALESCE(SUM(shares), 0)
      END AS shares
    FROM transaction_shares
    GROUP BY transaction_id, user_id;;

DELETE FROM transaction_shares;;

INSERT INTO transaction_shares (transaction_id, user_id, amount, shares)
    SELECT transaction_id, user_id, amount, shares
    FROM txs_agg;;

ALTER TABLE group_members ADD CONSTRAINT uq_group_members_group_user UNIQUE (group_id, user_id);

ALTER TABLE transaction_shares ADD CONSTRAINT uq_tx_shares_tx_user UNIQUE (transaction_id, user_id);

DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='transaction_shares'
          AND constraint_name='transaction_shares_transaction_id_fkey'
      ) THEN
        ALTER TABLE transaction_shares DROP CONSTRAINT transaction_shares_transaction_id_fkey;
      END IF;
    EXCEPTION WHEN others THEN
      -- не рушим миграцию, если имя было другим
      NULL;
    END$$;;

ALTER TABLE transaction_shares ADD CONSTRAINT transaction_shares_transaction_id_fkey FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE;

UPDATE alembic_version SET version_num='2025_08_08_groups_v2' WHERE alembic_version.version_num = '7b08661241e1';

-- Running upgrade 2025_08_08_groups_v2 -> 2025_08_15_money_and_indexes

ALTER TABLE transactions
            ALTER COLUMN amount TYPE NUMERIC(12,2)
            USING round((amount)::numeric, 2);

ALTER TABLE transaction_shares
            ALTER COLUMN amount TYPE NUMERIC(12,2)
            USING round((amount)::numeric, 2);

ALTER TABLE transactions ALTER COLUMN currency TYPE VARCHAR(3);

CREATE INDEX ix_tx_group_date ON transactions (group_id, date);

CREATE INDEX ix_txshare_tx ON transaction_shares (transaction_id);

CREATE INDEX ix_txshare_user ON transaction_shares (user_id);

UPDATE alembic_version SET version_num='2025_08_15_money_and_indexes' WHERE alembic_version.version_num = '2025_08_08_groups_v2';

-- Running upgrade 2025_08_15_money_and_indexes -> 2025_08_15_expense_categories_v2

SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'expense_categories'
              AND column_name = NULL;

