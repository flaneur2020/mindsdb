from mindsdb_sql.parser.dialects.mindsdb import CreatePredictor
from mindsdb_sql.parser.ast import Identifier, OrderBy

import mindsdb.api.mongo.functions as helpers
from mindsdb.api.mongo.classes import Responder
from mindsdb.api.mysql.mysql_proxy.libs.constants.response_type import RESPONSE_TYPE
from mindsdb.api.mongo.utilities import log
from mindsdb.integrations.libs.response import HandlerStatusResponse

from mindsdb.api.mongo.classes.query_sql import run_sql_command

class Responce(Responder):
    when = {'insert': helpers.is_true}

    def result(self, query, request_env, mindsdb_env, session):
        try:
            res = self._result(query, request_env, mindsdb_env)
        except Exception as e:
            log.error(e)
            res = {
                'n': 0,
                'writeErrors': [{
                    'index': 0,
                    'code': 0,
                    'errmsg': str(e)
                }],
                'ok': 1
            }
        return res

    def _result(self, query, request_env, mindsdb_env):
        table = query['insert']

        if table == 'databases':
            for doc in query['documents']:
                if '_id' in doc:
                    del doc['_id']
                for field in ('name', 'engine', 'connection_args'):
                    if field not in doc:
                        raise Exception(f"'{field}' must be specified")

                status = HandlerStatusResponse(success=False)
                try:
                    handler = mindsdb_env['integration_controller'].create_handler(
                        handler_type=doc['engine'],
                        connection_data=doc['connection_args']
                    )
                    status = handler.check_connection()
                except Exception as e:
                    status.error_message = str(e)

                if status.success is False:
                    raise Exception(f"Can't connect to db: {status.error_message}")

                integration = mindsdb_env['integration_controller'].get(doc['name'])
                if integration is not None:
                    raise Exception(f"Database '{doc['name']}' already exists.")

            for doc in query['documents']:
                mindsdb_env['integration_controller'].add(doc['name'], doc['engine'], doc['connection_args'])

            result = {
                "n": len(query['documents']),
                "ok": 1
            }
        elif table == 'predictors':
            predictors_columns = [
                'name',
                'status',
                'accuracy',
                'predict',
                'select_data_query',
                'training_options',
                'connection'
            ]

            models = mindsdb_env['model_controller'].get_models()

            if len(query['documents']) != 1:
                raise Exception("Must be inserted just one predictor at time")

            for doc in query['documents']:
                if '_id' in doc:
                    del doc['_id']

                bad_columns = [x for x in doc if x not in predictors_columns]
                if len(bad_columns) > 0:
                    raise Exception(f"Is no possible insert this columns to 'predictors' collection: {', '.join(bad_columns)}")

                if 'name' not in doc:
                    raise Exception("Please, specify 'name' field")

                if 'predict' not in doc:
                    raise Exception("Please, specify 'predict' field")

                if doc['name'] in [x['name'] for x in models]:
                    raise Exception(f"Predictor with name '{doc['name']}' already exists")

                select_data_query = doc.get('select_data_query')
                if select_data_query is None:
                    raise Exception("'select_data_query' must be in query")

                kwargs = doc.get('training_options', {})
                if 'timeseries_settings' in kwargs:
                    # mongo shell client sends int as float. need to convert it to int
                    for key in ('window', 'horizon'):
                        val = kwargs['timeseries_settings'].get(key)
                        if val is not None:
                            kwargs['timeseries_settings'][key] = int(val)

                integrations = mindsdb_env['integration_controller'].get_all().keys()
                connection = doc.get('connection')
                if connection is None:
                    if 'default_mongodb' in integrations:
                        connection = 'default_mongodb'
                    else:
                        for integration in integrations:
                            if integration.startswith('mongodb_'):
                                connection = integration
                                break

                if connection is None:
                    raise Exception("Can't find connection for data source")

                predict = doc['predict']
                if not isinstance(predict, list):
                    predict = [x.strip() for x in predict.split(',')]

                order_by = None
                group_by = None
                ts_settings = {}
                if 'timeseries_settings' in kwargs:
                    ts_settings = kwargs.pop('timeseries_settings')
                    if 'order_by' in ts_settings:
                        order_by = ts_settings['order_by']
                        if not isinstance(order_by, list):
                            order_by = [order_by]

                        order_by = [
                            OrderBy(Identifier(x))
                            for x in order_by
                        ]
                    if 'group_by' in ts_settings:
                        group_by = [
                            Identifier(x)
                            for x in ts_settings.get('group_by', [])
                        ]

                using = dict(kwargs)

                create_predictor_ast = CreatePredictor(
                    name=Identifier(doc['name']),
                    integration_name=Identifier(connection),
                    query_str=select_data_query,
                    targets=[Identifier(x) for x in predict],
                    order_by=order_by,
                    group_by=group_by,
                    window=ts_settings.get('window'),
                    horizon=ts_settings.get('horizon'),
                    using=using,
                )

                run_sql_command(mindsdb_env, create_predictor_ast)

            result = {
                "n": len(query['documents']),
                "ok": 1
            }
        else:
            raise Exception("Only insert to 'predictors' or 'databases' allowed")

        return result


responder = Responce()
