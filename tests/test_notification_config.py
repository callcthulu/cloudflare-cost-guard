"""Native channel config accepts references, never inline credentials."""
import copy
import unittest
from pathlib import Path

import test_config
from cfguard import config as module
from cfguard.config import ConfigError


def targets():
    return [
        {'id':'custom','type':'webhook','url_file':'/etc/cfguard/custom.url'},
        {'id':'ops-slack','type':'slack','url_file':'/etc/cfguard/slack.url'},
        {'id':'ops-discord','type':'discord','url_file':'/etc/cfguard/discord.url'},
        {'id':'ops-telegram','type':'telegram','token_file':'/etc/cfguard/bot.token',
         'chat_id_file':'/etc/cfguard/chat.id'},
        {'id':'ops-email','type':'email','settings_file':'/etc/cfguard/smtp.json'},
    ]


class NativeNotificationConfigTests(unittest.TestCase):
    load = test_config.ConfigTests.load

    def test_all_channels_parse_without_opening_credentials_and_enumerate_protected_files(self):
        raw=test_config.example()
        raw['notification']={'targets':targets(),'max_attempts':3}
        config=self.load(raw)
        self.assertEqual(len(config.notification['targets']),5)
        self.assertTrue(hasattr(module,'notification_secret_files'), 'installer secret enumeration missing')
        self.assertEqual(set(module.notification_secret_files(config.notification)),
                         {Path('/etc/cfguard/'+p) for p in ('custom.url','slack.url','discord.url','bot.token','chat.id','smtp.json')})

    def test_legacy_webhook_configuration_stays_compatible(self):
        raw=test_config.example()
        raw['notification']={'url_file':'/etc/cfguard/legacy.url'}
        config=self.load(raw)
        self.assertEqual(config.notification, {'url_file':Path('/etc/cfguard/legacy.url'),'max_attempts':3})
        self.assertTrue(hasattr(module,'notification_secret_files'), 'installer secret enumeration missing')
        self.assertEqual(module.notification_secret_files(config.notification),(Path('/etc/cfguard/legacy.url'),))
        self.assertEqual(module.notification_secret_files(None),())

    def test_reject_ambiguous_unsafe_or_incomplete_native_configuration(self):
        cases=[{'targets':[]},{'targets':targets(),'url_file':'/etc/cfguard/legacy.url'},
               {'targets':'slack'},{'targets':[targets()[0]]*2},{'targets':[targets()[0]],'max_attempts':True},
               {'targets':[targets()[0]],'max_attempts':11},{}]
        for field,value in [('id','bad id'),('id','a\nsecret'),('id','A'),('type','arbitrary-plugin'),
                            ('url_file','relative.url'),('url','https://inline.example.invalid/private'),
                            ('token','INLINE_NOT_ALLOWED')]:
            target=copy.deepcopy(targets()[0]);target[field]=value;cases.append({'targets':[target]})
        for target in targets():
            item=copy.deepcopy(target)
            pathfield=next(k for k in item if k.endswith('_file'))
            del item[pathfield];cases.append({'targets':[item]})
        too_many=[dict(targets()[0],id='target-'+str(i)) for i in range(17)]
        cases.append({'targets':too_many})
        for notification in cases:
            with self.subTest(notification=notification), self.assertRaises(ConfigError):
                raw=test_config.example();raw['notification']=notification;self.load(raw)

    def test_maximum_targets_is_supported_and_paths_remain_external_references(self):
        raw=test_config.example()
        raw['notification']={'targets':[dict(targets()[0],id='target-'+str(i)) for i in range(16)],'max_attempts':10}
        config=self.load(raw)
        self.assertEqual(len(config.notification['targets']),16)
        self.assertEqual(config.notification['targets'][0]['url_file'],Path('/etc/cfguard/custom.url'))
