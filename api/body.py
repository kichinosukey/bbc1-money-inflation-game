# -*- coding: utf-8 -*-
"""
Copyright (c) 2019 beyond-blockchain.org.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import bbc1
import binascii
import datetime
import hashlib
import os
import string
import sys
import time

from bbc1.core import bbc_app, bbclib
from bbc1.core.bbc_config import DEFAULT_CORE_PORT
from bbc1.lib import id_lib, token_lib
from bbc1.lib.app_support_lib import Database, TransactionLabel
from bbc1.lib.app_support_lib import get_timestamp_in_seconds
from flask import Blueprint, request, abort, jsonify, g


NAME_OF_DB = 'payment_db'


payment_user_table_definition = [
    ["user_id", "BLOB"],
    ["name", "TEXT"],
    ["public_key", "BLOB"],
    ["private_key", "BLOB"],
]

payment_tx_table_definition = [
    ["tx_id", "BLOB"],
    ["timestamp", "INTEGER"],
    ["mint_id", "BLOB"],
    ["from_name", "TEXT"],
    ["to_name", "TEXT"],
    ["amount", "TEXT"],
    ["label", "TEXT"],
]

IDX_USER_ID = 0
IDX_NAME    = 1
IDX_PUBKEY  = 2
IDX_PRIVKEY = 3

IDX_TX_ID     = 0
IDX_TIMESTAMP = 1
IDX_MINT_ID   = 2
IDX_FROM      = 3
IDX_TO        = 4
IDX_AMOUNT    = 5
IDX_LABEL     = 6

LABEL_JOINED = '__joined__'
LABEL_SALT = 'label salt'


domain_id = bbclib.get_new_id("loochs", include_timestamp=False)
label_group_id = bbclib.get_new_id("loochs_labels", include_timestamp=False)


class User:

    def __init__(self, user_id, name, keypair):
        self.user_id = user_id
        self.name = name
        self.keypair = keypair


    @staticmethod
    def from_row(row):
        return User(
            row[IDX_USER_ID],
            row[IDX_NAME],
            bbclib.KeyPair(privkey=row[IDX_PRIVKEY], pubkey=row[IDX_PUBKEY])
        )


class Store:

    def __init__(self):
        self.db = Database()
        self.db.setup_db(domain_id, NAME_OF_DB)


    def close(self):
        self.db.close_db(domain_id, NAME_OF_DB)


    def get_tx_list(self, mint, name=None, count=None, offset=None,
            basetime=None):
        if basetime is None:
            basetime = 0
        else:
            basetime = int(basetime)

        if offset is None:
            offset = 0
        else:
            offset = int(offset)

        if count is not None:
            s_limit = ' limit {0}, {1}'.format(offset, count)
        else:
            s_limit = ''

        mint_id = mint.mint_id
        symbol = mint.get_currency_spec().symbol

        if name is not None:
            rows = self.db.exec_sql(
                domain_id,
                NAME_OF_DB,
                'select * from tx_table where mint_id=? ' + \
                'and timestamp>=? ' + \
                'and (from_name=? or to_name=?) order by rowid desc' + s_limit,
                mint_id,
                basetime,
                name,
                name
            )
            counts = self.db.exec_sql(
                domain_id,
                NAME_OF_DB,
                'select count(*) from tx_table where mint_id=? ' + \
                'and timestamp>=? ' + \
                'and (from_name=? or to_name=?)',
                mint_id,
                basetime,
                name,
                name
            )

        else:
            rows = self.db.exec_sql(
                domain_id,
                NAME_OF_DB,
                'select * from tx_table where mint_id=? ' + \
                'and timestamp>=? ' + \
                'order by rowid desc' + s_limit,
                mint_id,
                basetime,
            )
            counts = self.db.exec_sql(
                domain_id,
                NAME_OF_DB,
                'select count(*) from tx_table where mint_id=? ' + \
                'and timestamp>=?',
                mint_id,
                basetime
            )

        number = int(counts[0][0])

        dics = []
        for row in rows:
            dics.append({
                'timestamp': row[IDX_TIMESTAMP],
                'from_name': row[IDX_FROM],
                'to_name': row[IDX_TO],
                'amount': row[IDX_AMOUNT],
                'label': row[IDX_LABEL]
            })
        return {
            'count_before': offset,
            'count_after': number - offset - len(rows),
            'transactions': dics,
            'symbol': symbol
        }

    def get_user(self, user_id, table):
        rows = self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'select * from ' + table + ' where user_id=?',
            user_id
        )
        if len(rows) <= 0:
            return None
        return User.from_row(rows[0])


    def get_users(self, table):
        rows = self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'select * from ' + table
        )
        users = []
        for row in rows:
            users.append(User.from_row(row))
        return users


    def read_user(self, name, table):
        rows = self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'select * from ' + table + ' where name=?',
            name
        )
        if len(rows) <= 0:
            return None
        return User.from_row(rows[0])


    def setup(self):
        self.db.create_table_in_db(domain_id, NAME_OF_DB, 'user_table',
                payment_user_table_definition, primary_key=IDX_USER_ID,
                indices=[IDX_NAME])
        self.db.create_table_in_db(domain_id, NAME_OF_DB, 'currency_table',
                payment_user_table_definition, primary_key=IDX_USER_ID,
                indices=[IDX_NAME])
        self.db.create_table_in_db(domain_id, NAME_OF_DB, 'tx_table',
                payment_tx_table_definition, primary_key=IDX_TX_ID,
                indices=[IDX_MINT_ID, IDX_FROM, IDX_TO])


    def update_user(self, user, table):
        self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'update ' + table + ' set public_key=?, private_key=? ' + \
            'where user_id=?',
            user.keypair.public_key,
            user.keypair.private_key,
            user.user_id
        )


    def user_exists(self, name, table):
        rows = self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'select rowid from ' + table + ' where name=?',
            name
        )
        return len(rows) > 0


    def write_tx(self, tx_id, timestamp, mint_id, from_name, to_name, amount,
            label):
        self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'insert into tx_table values (?, ?, ?, ?, ?, ?, ?)',
            tx_id,
            timestamp,
            mint_id,
            from_name,
            to_name,
            amount,
            label
        )


    def write_user(self, user, table):
        self.db.exec_sql(
            domain_id,
            NAME_OF_DB,
            'insert into ' + table + ' values (?, ?, ?, ?)',
            user.user_id,
            user.name,
            user.keypair.public_key,
            user.keypair.private_key
        )


def abort_by_bad_content_type(content_type):
    abort(400, {
        'code': 'Bad Request',
        'message': 'Content-Type {0} is not expected'.format(content_type)
    })


def abort_by_missing_param(param):
    abort(400, {
        'code': 'Bad Request',
        'message': '{0} is missing'.format(param)
    })


def get_balances_of(user_id, currencies):
    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)

    dics = []
    for currency in currencies:
        mint = token_lib.BBcMint(domain_id, currency.user_id, currency.user_id,
                g.idPubkeyMap)
        currency_spec = mint.get_currency_spec()
        value = mint.get_balance_of(user_id)
        mint.close()

        dics.append({
            'balance': ("{0:.%df}" % (currency_spec.decimal)).format(
                    value / (10 ** currency_spec.decimal)),
            'symbol': currency_spec.symbol,
            'mint_id': binascii.b2a_hex(currency.user_id).decode()
        })

    return dics


def from_hex_to_user(g, hex_id, table):
    user_id = bytes(binascii.a2b_hex(hex_id))
    user = g.store.get_user(user_id, table)
    if user is None:
        abort(404, {
            'code': 'Not Found',
            'message': 'user/currency {0} is not found'.format(hex_id)
        })

    return user


api = Blueprint('api', __name__)


@api.after_request
def after_request(response):
    g.store.close()

    if g.idPubkeyMap is not None:
        g.idPubkeyMap.close()
    if g.mint is not None:
        g.mint.close()

    return response


@api.before_request
def before_request():
    g.store = Store()
    g.idPubkeyMap = None
    g.mint = None


@api.route('/')
def index():
    return jsonify({})


@api.route('/currency', methods=['GET'])
def list_currencies():
    name = request.args.get('name')

    if name is None:
        users = g.store.get_users('currency_table')
        dics = []
        for user in users:
            dics.append({
                'name': user.name,
                'mint_id': binascii.b2a_hex(user.user_id).decode()
            })
        return jsonify({'currencies': dics})

    user = g.store.read_user(name, 'currency_table')
    if user is None:
        abort(404, {
            'code': 'Not Found',
            'message': 'currency {0} is not found'.format(name)
        })

    return jsonify({
        'name': name,
        'mint_id': binascii.b2a_hex(user.user_id).decode()
    })

@api.route('/currency/<string:hex_mint_id>', methods=['GET'])
def get_currency_unique(hex_mint_id=None):
    if hex_mint_id is None:
        abort_by_missing_param('mint_id')

    user = g.store.get_user(binascii.a2b_hex(hex_mint_id), 'currency_table')

    if user is None:
        abort(404, {
            'code': 'Not Found',
            'message': 'mint_id {0} is not found'.format(hex_mint_id)
        })

    return jsonify({
        'name': user.name,
        'mint_id': binascii.b2a_hex(user.user_id).decode()
    })

@api.route('/currency', methods=['POST'])
def define_currency():
    if request.headers['Content-Type'] != 'application/json':
        abort_by_bad_content_type(request.headers['Content-Type'])

    name = request.json.get('name')
    symbol = request.json.get('symbol')

    if name is None:
        abort_by_missing_param('name')
    if symbol is None:
        abort_by_missing_param('symbol')
    if g.store.user_exists(name, 'currency_table'):
        abort(409, {
            'code': 'Conflict',
            'message': 'currency {0} is already defined'.format(name)
        })
    if g.store.user_exists(name, 'user_table'):
        abort(409, {
            'code': 'Conflict',
            'message': '{0} is already defined as a user name'.format(name)
        })

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    mint_id, keypairs = g.idPubkeyMap.create_user_id(num_pubkeys=1)

    currency_spec = token_lib.CurrencySpec(request.json)

    g.mint = token_lib.BBcMint(domain_id, mint_id, mint_id, g.idPubkeyMap)
    g.mint.set_condition(0, keypair=keypairs[0])
    g.mint.set_currency_spec(currency_spec, keypair=keypairs[0])

    g.store.write_user(User(mint_id, name, keypairs[0]), 'currency_table')

    return jsonify({
        'name': name,
        'symbol': symbol,
        'mint_id': binascii.b2a_hex(mint_id).decode()
    })


@api.route('/issue/<string:hex_mint_id>', methods=['POST'])
def issue_to_user(hex_mint_id=None):
    if hex_mint_id is None:
        abort_by_missing_param('mint_id')

    currency = from_hex_to_user(g, hex_mint_id, 'currency_table')

    hex_user_id = request.form.get('user_id')
    amount = request.form.get('amount')

    s_label = LABEL_JOINED
    label_id = TransactionLabel.create_label_id(s_label, LABEL_SALT)
    label = TransactionLabel(label_group_id, label_id=label_id)

    if hex_user_id is None:
        abort_by_missing_param('user_id')
    if amount is None:
        abort_by_missing_param('amount')

    user = from_hex_to_user(g, hex_user_id, 'user_table')

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    g.mint = token_lib.BBcMint(domain_id, currency.user_id, currency.user_id,
            g.idPubkeyMap)

    currency_spec = g.mint.get_currency_spec()
    value = int(float(amount) * (10 ** currency_spec.decimal))

    tx = g.mint.issue(user.user_id, value, keypair=currency.keypair,
            label=label)

    g.store.write_tx(tx.transaction_id, get_timestamp_in_seconds(tx),
            currency.user_id, '', user.name, amount, s_label)

    return jsonify({
        'amount': ('{0:.%df}' % (currency_spec.decimal)).format(
                value / (10 ** currency_spec.decimal)),
        'symbol': currency_spec.symbol
    })


@api.route('/new-keypair/<string:hex_user_id>', methods=['POST'])
def replace_keypair(hex_user_id=None):
    if hex_user_id is None:
        abort_by_missing_param('user_id')

    user = from_hex_to_user(g, hex_user_id, 'user_table')
    keypair_old = user.keypair

    keypair = bbclib.KeyPair()
    keypair.generate()

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    g.idPubkeyMap.update(user.user_id,
            public_keys_to_replace=[keypair.public_key], keypair=keypair_old)
    
    user.keypair = keypair
    g.store.update_user(user, 'user_table')

    return jsonify({
        'old_pubkey': binascii.b2a_hex(keypair_old.public_key).decode(),
        'new_pubkey': binascii.b2a_hex(keypair.public_key).decode()
    })


@api.route('/setup', methods=['POST'])
def setup():
    g.store.setup()

    tmpclient = bbc_app.BBcAppClient(port=DEFAULT_CORE_PORT, multiq=False,
            loglevel="all")
    tmpclient.domain_setup(domain_id)
    tmpclient.callback.synchronize()
    tmpclient.unregister_from_core()
    return jsonify({'domain_id': binascii.b2a_hex(domain_id).decode()})


# @api.route('/set-condition', methods=['POST'])
# def set_condition():
#     return jsonify({})


@api.route('/status/<string:hex_user_id>', methods=['GET'])
def show_user(hex_user_id=None):
    if hex_user_id is None:
        abort_by_missing_param('user_id')

    user = from_hex_to_user(g, hex_user_id, 'user_table')

    hex_mint_id = request.args.get('mint_id')

    if hex_mint_id is None:
        currencies = g.store.get_users('currency_table')
        return jsonify(get_balances_of(user.user_id, currencies))

    currency = from_hex_to_user(g, hex_mint_id, 'currency_table')
    return jsonify(get_balances_of(user.user_id, [currency])[0])


@api.route('/swap/<string:hex_mint_id>/<string:hex_counter_mint_id>',
        methods=['POST'])
def swap_between_users(hex_mint_id=None, hex_counter_mint_id=None):
    if hex_mint_id is None:
        abort_by_missing_param('mint_id')
    if hex_counter_mint_id is None:
        abort_by_missing_param('counter_mint_id')

    currency = from_hex_to_user(g, hex_mint_id, 'currency_table')
    counter_currency = from_hex_to_user(g, hex_counter_mint_id,
            'currency_table')

    hex_user_id = request.form.get('user_id')
    hex_counter_user_id = request.form.get('counter_user_id')
    amount = request.form.get('amount')
    counter_amount = request.form.get('counter_amount')
    s_label = request.form.get('label')

    if s_label is None or len(s_label) <= 0:
        s_label = ''
        label = None
    else:
        label_id = TransactionLabel.create_label_id(s_label, LABEL_SALT)
        label = TransactionLabel(label_group_id, label_id=label_id)

    if hex_user_id is None:
        abort_by_missing_param('user_id')
    if hex_counter_user_id is None:
        abort_by_missing_param('counter_user_id')
    if amount is None:
        abort_by_missing_param('amount')
    if counter_amount is None:
        abort_by_missing_param('counter_amount')

    user = from_hex_to_user(g, hex_user_id, 'user_table')
    counter_user = from_hex_to_user(g, hex_counter_user_id, 'user_table')

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    g.mint = token_lib.BBcMint(domain_id, currency.user_id, currency.user_id,
            g.idPubkeyMap)
    counter_mint = token_lib.BBcMint(domain_id, counter_currency.user_id,
            counter_currency.user_id, g.idPubkeyMap)

    currency_spec = g.mint.get_currency_spec()
    counter_currency_spec = counter_mint.get_currency_spec()
    value = int(float(amount) * (10 ** currency_spec.decimal))
    counter_value = int(
            float(counter_amount) * (10 ** counter_currency_spec.decimal))

    tx = g.mint.swap(counter_mint, user.user_id, counter_user.user_id,
            value, counter_value,
            keypair_this=user.keypair, keypair_that=counter_user.keypair,
            keypair_mint=currency.keypair,
            keypair_counter_mint=counter_currency.keypair)
    counter_mint.close()

    g.store.write_tx(tx.transaction_id, get_timestamp_in_seconds(tx),
            currency.user_id, user.user_id, counter_user.user_id, amount,
            s_label)
    counter_txid = bytearray(tx.transaction_id)
    counter_txid.extend(b'00')
    g.store.write_tx(bytes(counter_tx_id), get_timestamp_in_seconds(tx),
            counter_currency.user_id, counter_user.user_id, user.user_id,
            counter_amount, s_label)


    return jsonify({
        'amount': ('{0:.%df}' % (currency_spec.decimal)).format(
                value / (10 ** currency_spec.decimal)),
        'symbol': currency_spec.symbol,
        'counter_amount': ('{0:.%df}'
                % (counter_currency_spec.decimal)).format(
                counter_value / (10 ** counter_currency_spec.decimal)),
        'counter_symbol': counter_currency_spec.symbol
    })


@api.route('/transactions/<string:hex_mint_id>', methods=['GET'])
def show_transactions(hex_mint_id=None):
    if hex_mint_id is None:
        abort_by_missing_param('mint_id')

    mint_id = bytes(binascii.a2b_hex(hex_mint_id))
    mint = token_lib.BBcMint(domain_id, mint_id, mint_id, g.idPubkeyMap)

    name = request.args.get('name')
    count = request.args.get('count')
    offset = request.args.get('offset')
    basetime = request.args.get('basetime')

    return jsonify(g.store.get_tx_list(mint, name=name, count=count,
            offset=offset, basetime=basetime))


@api.route('/transfer/<string:hex_mint_id>', methods=['POST'])
def transfer_to_user(hex_mint_id=None):
    if hex_mint_id is None:
        abort_by_missing_param('mint_id')

    currency = from_hex_to_user(g, hex_mint_id, 'currency_table')

    hex_from_user_id = request.form.get('from_user_id')
    hex_to_user_id = request.form.get('to_user_id')
    amount = request.form.get('amount')
    s_label = request.form.get('label')

    if s_label is None or len(s_label) <= 0:
        s_label = ''
        label = None
    else:
        label_id = TransactionLabel.create_label_id(s_label, LABEL_SALT)
        label = TransactionLabel(label_group_id, label_id=label_id)

    if hex_from_user_id is None:
        abort_by_missing_param('from_user_id')
    if hex_to_user_id is None:
        abort_by_missing_param('to_user_id')
    if amount is None:
        abort_by_missing_param('amount')

    from_user = from_hex_to_user(g, hex_from_user_id, 'user_table')
    to_user = from_hex_to_user(g, hex_to_user_id, 'user_table')

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    g.mint = token_lib.BBcMint(domain_id, currency.user_id, currency.user_id,
            g.idPubkeyMap)

    currency_spec = g.mint.get_currency_spec()
    value = int(float(amount) * (10 ** currency_spec.decimal))

    tx = g.mint.transfer(from_user.user_id, to_user.user_id, value,
            keypair_from=from_user.keypair, keypair_mint=currency.keypair)

    g.store.write_tx(tx.transaction_id, get_timestamp_in_seconds(tx),
            currency.user_id, from_user.name, to_user.name, amount, s_label)

    return jsonify({
        'amount': ('{0:.%df}' % (currency_spec.decimal)).format(
                value / (10 ** currency_spec.decimal)),
        'symbol': currency_spec.symbol
    })


@api.route('/user', methods=['GET'])
def list_users():
    name = request.args.get('name')

    if name is None:
        users = g.store.get_users('user_table')
        dics = []
        for user in users:
            dics.append({
                'name': user.name,
                'user_id': binascii.b2a_hex(user.user_id).decode()
            })
        return jsonify({'users': dics})

    else:
        user = g.store.read_user(name, 'user_table')
        if user is None:
            abort(404, {
                'code': 'Not Found',
                'message': 'user {0} is not found'.format(name)
            })

        return jsonify({
            'name': name,
            'user_id': binascii.b2a_hex(user.user_id).decode()
        })


@api.route('/user', methods=['POST'])
def define_user():
    name = request.form.get('name')

    if name is None:
        abort_by_missing_param('name')
    if g.store.user_exists(name, 'user_table'):
        abort(409, {
            'code': 'Conflict',
            'message': 'user {0} is already defined'.format(name)
        })
    if g.store.user_exists(name, 'currency_table'):
        abort(409, {
            'code': 'Conflict',
            'message': '{0} is already defined as a currency name'.format(name)
        })

    g.idPubkeyMap = id_lib.BBcIdPublickeyMap(domain_id)
    user_id, keypairs = g.idPubkeyMap.create_user_id(num_pubkeys=1)

    g.store.write_user(User(user_id, name, keypairs[0]), 'user_table')

    return jsonify({
        'name': name,
        'user_id': binascii.b2a_hex(user_id).decode()
    }), 201


@api.errorhandler(400)
@api.errorhandler(404)
@api.errorhandler(409)
def error_handler(error):
    return jsonify({'error': {
        'code': error.description['code'],
        'message': error.description['message']
    }}), error.code


# end of api/body.py
