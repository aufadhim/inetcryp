import unittest
from pathlib import Path
from html.parser import HTMLParser


class Ids(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        value=dict(attrs).get('id')
        if value:self.ids.append(value)


class WorkspaceTests(unittest.TestCase):
    def test_navigation_targets_unique_and_preserve_old_controls(self):
        text=Path('static/index.html').read_text(encoding='utf-8')
        parser=Ids();parser.feed(text)
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        for name in ('overview','radar','research','terminal','screener','paper','backtester','settings'):
            self.assertIn('tab-'+name,parser.ids)
            self.assertIn('tabBtn-'+name,parser.ids)
        for control in ('ptEquity','btSymbol','candleChartContainer','symbolInput'):
            self.assertIn(control,parser.ids)

    def test_modules_no_longer_prepend_into_all_views(self):
        for filename,mount in (('research-lab.js','research-mount'),('anomaly-radar.js','radar-mount')):
            text=(Path('static/js')/filename).read_text(encoding='utf-8')
            self.assertIn(mount,text)
            self.assertNotIn("querySelector('main').prepend",text)

    def test_portfolio_event_comes_from_paper_not_market_response(self):
        text=Path('static/index.html').read_text(encoding='utf-8')
        self.assertEqual(text.count("new CustomEvent('inetcryp:paper'"),1)
        paper_function=text.split('async function loadPaperTrading()',1)[1]
        self.assertIn("new CustomEvent('inetcryp:paper'",paper_function)
        self.assertIn("if(document.body.dataset.page !== 'terminal') return",text)
