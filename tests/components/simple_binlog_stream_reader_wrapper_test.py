# -*- coding: utf-8 -*-
# Copyright 2016 Yelp Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import absolute_import
from __future__ import unicode_literals

from datetime import datetime

import mock
import pytest
from pymysqlreplication.event import GtidEvent
from pymysqlreplication.event import QueryEvent

from replication_handler.components.simple_binlog_stream_reader_wrapper import SimpleBinlogStreamReaderWrapper
from replication_handler.util.misc import DataEvent
from replication_handler.util.misc import ReplicationHandlerEvent
from replication_handler.util.position import GtidPosition
from replication_handler.util.position import LogPosition


class TestSimpleBinlogStreamReaderWrapper(object):

    @pytest.yield_fixture
    def patch_stream(self):
        with mock.patch(
            'replication_handler.components.simple_binlog_stream_reader_wrapper.LowLevelBinlogStreamReaderWrapper'
        ) as mock_stream:
            yield mock_stream

    def test_yield_events_when_gtid_enabled(self, mock_db_connections, patch_stream):
        gtid_event_0 = mock.Mock(spec=GtidEvent, gtid="sid:11")
        query_event_0 = mock.Mock(spec=QueryEvent)
        query_event_1 = mock.Mock(spec=QueryEvent)
        gtid_event_1 = mock.Mock(spec=GtidEvent, gtid="sid:12")
        data_event_0 = mock.Mock(spec=DataEvent)
        data_event_1 = mock.Mock(spec=DataEvent)
        data_event_2 = mock.Mock(spec=DataEvent)
        event_list = [
            gtid_event_0,
            query_event_0,
            data_event_0,
            data_event_1,
            data_event_2,
            gtid_event_1,
            query_event_1,
        ]
        patch_stream.return_value.peek.side_effect = event_list
        patch_stream.return_value.pop.side_effect = event_list
        # set offset to 1, meaning we want to skip event at offset 0
        stream = SimpleBinlogStreamReaderWrapper(
            mock_db_connections.source_database_config,
            mock_db_connections.tracker_database_config,
            GtidPosition(
                gtid="sid:10",
                offset=1
            ),
            gtid_enabled=True
        )
        results = [
            ReplicationHandlerEvent(
                event=data_event_1,
                position=GtidPosition(gtid="sid:11", offset=2)
            ),
            ReplicationHandlerEvent(
                event=data_event_2,
                position=GtidPosition(gtid="sid:11", offset=3)
            ),
            ReplicationHandlerEvent(
                event=query_event_1,
                position=GtidPosition(gtid="sid:12", offset=0)
            )
        ]
        for replication_event, result in zip(stream, results):
            assert replication_event.event == result.event
            assert replication_event.position.gtid == result.position.gtid
            assert replication_event.position.offset == result.position.offset

    def test_meteorite_and_sensu_alert(
        self,
        mock_db_connections,
        patch_stream
    ):
        if not SimpleBinlogStreamReaderWrapper.is_meteorite_sensu_supported():
            pytest.skip("meteorite and sensu are unsupported in open source version.")

        from data_pipeline.tools.meteorite_gauge_manager import MeteoriteGaugeManager
        from data_pipeline.tools.sensu_alert_manager import SensuAlertManager
        with mock.patch.object(
            MeteoriteGaugeManager,
            'periodic_process'
        ) as mock_meteorite, mock.patch.object(
            SensuAlertManager,
            'periodic_process'
        ) as mock_sensu_alert:
            stream, results = self._setup_stream_and_expected_result(
                mock_db_connections.source_database_config,
                mock_db_connections.tracker_database_config,
                patch_stream
            )
            assert mock_meteorite.call_count == 1
            assert mock_sensu_alert.call_count == 1

    def test_yield_event_with_heartbeat_event(
        self,
        mock_db_connections,
        patch_stream,
    ):
        stream, results = self._setup_stream_and_expected_result(
            mock_db_connections.source_database_config,
            mock_db_connections.tracker_database_config,
            patch_stream
        )
        for replication_event, result in zip(stream, results):
            assert replication_event.event == result.event
            assert replication_event.position.log_pos == result.position.log_pos
            assert replication_event.position.log_file == result.position.log_file
            assert replication_event.position.offset == result.position.offset
            assert replication_event.position.hb_serial == result.position.hb_serial
            assert replication_event.position.hb_timestamp == result.position.hb_timestamp

    def _setup_stream_and_expected_result(
        self,
        source_database_config,
        tracker_database_config,
        patch_stream
    ):
        log_pos = 10
        log_file = "binlog.001"
        row = {"after_values": {
            "serial": 123,
            # This timestamp is Wed, 21 Oct 2015 12:05:27 GMT
            "timestamp": datetime.fromtimestamp(1445429127)
        }}
        heartbeat_event = mock.Mock(
            spec=DataEvent,
            schema='yelp_heartbeat',
            log_pos=log_pos,
            log_file=log_file,
            row=row
        )
        data_event_0 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        data_event_1 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        data_event_2 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        event_list = [
            heartbeat_event,
            data_event_0,
            data_event_1,
            data_event_2,
        ]
        patch_stream.return_value.peek.side_effect = event_list
        patch_stream.return_value.pop.side_effect = event_list
        stream = SimpleBinlogStreamReaderWrapper(
            source_database_config,
            tracker_database_config,
            LogPosition(
                log_pos=log_pos,
                log_file=log_file,
                offset=0
            ),
            gtid_enabled=False,
        )
        # Since the offset is 0, so the result should start offset 1, and skip
        # data_event_0 which is at offset 0.
        results = [
            ReplicationHandlerEvent(
                event=data_event_1,
                position=LogPosition(
                    log_pos=log_pos,
                    log_file=log_file,
                    offset=1,
                    hb_serial=123,
                    # This is Wed, 21 Oct 2015 12:05:27 GMT
                    hb_timestamp=1445429127,
                )
            ),
            ReplicationHandlerEvent(
                event=data_event_2,
                position=LogPosition(
                    log_pos=log_pos,
                    log_file=log_file,
                    offset=2,
                    hb_serial=123,
                    # This is Wed, 21 Oct 2015 12:05:27 GMT
                    hb_timestamp=1445429127,
                )
            )
        ]
        return stream, results
