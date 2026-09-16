import copy
import json
import tempfile
import unittest
from pathlib import Path
from mapper_core import MapperState, SRV_FLAG


class MapValidationTests(unittest.TestCase):
    def setUp(self):
        self.state = MapperState()
        self.state.process_status(dict(Flags=SRV_FLAG,Latitude=38,Longitude=-9,Heading=0))
        self.data = copy.deepcopy(self.state.to_dict())

    def test_invalid_maps_leave_existing_state_unchanged(self):
        invalid = [dict(planet_radius=0), dict(center_lat=float('nan')),
                   dict(search_started=True,datum_lat=None), dict(route_index=999),
                   dict(deposits=[dict(x=0,y=0,lat=38,lon=-9,name='A',size='Grande',rigs='abc')]),
                   dict(route_history=[dict(x=0,y=0,number=1,status='invalid')])]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'map.json'
            for changes in invalid:
                with self.subTest(changes=changes):
                    path.write_text(json.dumps(dict(self.data,**changes)),encoding='utf-8')
                    with self.assertRaises((ValueError,TypeError)):
                        self.state.load(path)
                    self.assertEqual(self.state.to_dict(),self.data)

    def test_legacy_marker_coordinates_are_reconstructed(self):
        self.data['deposits'] = [dict(x=0,y=0,name='Antigo')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'map.json'
            path.write_text(json.dumps(self.data),encoding='utf-8')
            self.state.load(path)
        deposit = self.state.deposits[0]
        self.assertEqual((deposit['lat'],deposit['lon']),(38,-9))
        self.assertEqual((deposit['size'],deposit['rigs']),('Pequeno',1))
