from base64 import b64decode
from cloudscraper import create_scraper
from lxml.etree import HTML
from re import findall as re_findall
from requests import post

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException


class SiteList():
    def __init__(self):
        self._load_site_list()

    @property
    def dood_list(self):
        return self._dood_site

    @property
    def fembed_list(self):
        return self._fmed_list

    @property
    def lionwish_list(self):
        return self._lion_wish

    @property
    def shortest_list(self):
        return self._shortest_list

    @property
    def gd_sharer(self):
        return self._gd_sharer

    @property
    def passvip_list(self):
        return self._passvip_list

    @property
    def tera_list(self):
        return self._tera_site

    @property
    def stape_list(self):
        return self._stape_site

    @property
    def ddl_list(self):
        return tuple(sorted(self._files_hoster + self._videos_hoster + self.fembed_list + self.gd_sharer))

    @property
    def bypass_list(self):
        return tuple(sorted(self._bypass_sites + self._passvip_list + self._shortest_list + self.aio_bypass_list))

    @property
    def aio_bypass_list(self):
        aio_one, aio_two, aio_three = self.aio_bypass_dict()
        return tuple(aio_one.keys()) + tuple(aio_two.keys()) + tuple(aio_three.keys())

    def _load_site_list(self):
        self._dood_site = ('dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws', 'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf',
                           'dood.re', 'dood.video', 'dooood.com', 'dood.yt', 'doods.yt', 'dood.stream', 'doods.pro', 'ds2play.com', 'dood.zip', 'poops.media', 'ds2video.com')
        self._files_hoster = ('1fichier.com', 'antfiles.com', 'github.com', 'gofile.io', 'hxfile.co', 'krakenfiles.com', 'letsupload.io', 'mdisk.me',
                              'mediafire.com', 'onedrive.com', 'osdn.net', 'pixeldrain.com', 'racaty.net', 'romsget.io', 'send.cm', 'sfile.mobi',
                              'solidfiles.com', 'sourceforge.net', 'uploadbaz.me', 'upload.ee', 'uploadhaven.com', 'uppit.com', 'uptobox.com',
                              'userscloud.com', 'wetransfer.com', 'yandex.com', 'zippyshare.com', 'racaty.io')
        self._videos_hoster = ('mp4upload.com', 'streamlare.com', 'streamtape.com')
        self._lion_wish = ('vidhide.com', 'vidhidepro.com', 'filelions.site', 'filelions.live', 'filelions.to', 'filelions.online', 'cabecabean.lol', 'embedwish.com',
                           'streamwish.com', 'kitabmarkaz.xyz', 'wishfast.top', 'streamwish.to')
        self._tera_site = ('terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 'momerybox.com', 'teraboxapp.com', '1024tera.com', 'terabox.app')
        self._gd_sharer = ('appdrive', 'gdtot', 'gdflix', 'sharer')
        self._fmed_list = ('fembed.net', 'fembed.com', 'femax20.com', 'fcdn.stream', 'feurl.com', 'layarkacaxxi.icu', 'naniplay.nanime.in', 'naniplay.nanime.biz',
                           'naniplay.com', 'mm9842.com' 'javcl.me', 'asianclub.tv', 'javhdfree.icu', 'sexhd.co', 'vanfem.com')
        self._stape_site = ('streamtape.com', 'streamtape.co', 'streamtape.cc', 'streamtape.to', 'streamtape.net', 'streamta.pe', 'streamtape.xyz')
        self._bypass_sites = ('adf.ly', 'droplink.co', 'filecrypt.co', 'gplinks.co', 'gtlinks.me', 'theforyou.in', 'kinemaster.cc', 'hypershort.com', 'ouo.io',
                              'rocklinks.net', 'shortly.xyz', 'sirigan.my.id', 'thinfi.com', 'tinyurl.com', 'try2link.com', 'psa.pm', 'pkin.me',
                              'bluemediafile.site', 'tnlink.in', 'linkvertise.com', 'earnl.xyz', 'rslinks.net', 'bit.ly', 'mdisk.pro')
        self._passvip_list = ('boost.ink', 'exe.io', 'exey.io', 'goo.gl', 'mboost.me', 'ph.apps2app.com', 'rekonise.com', 'shrto.ml',
                              'shortconnect.com', 'social-unlock.com', 'sub2unlock.com', 'sub2unlock.net', 'sub4unlock.com', 't.co', 'ytsubme.com')
        self._shortest_list = ('shorte.st', 'festyy.com', 'cllkme.com', 'estyy.com', 'gestyy.com', 'corneey.com', 'destyy.com', 'ceesty.com')

    @staticmethod
    def aio_bypass_dict():
        shortner_dict_one = {'tekcrypt.in': ['https://tekcrypt.in/tek/', 20],
                             'indianshortner.in': ['https://indianshortner.com/', 5],
                             'open.crazyblog.in': ['https://hr.vikashmewada.com/', 7],
                             'tnvalue.in': ['https://internet.webhostingtips.club/', 5],
                             'shortingly.me': ['https://go.techyjeeshan.xyz/', 5],
                             'bindaaslinks.com': ['https://www.techishant.in/blog/', 5],
                             'pdiskshortener.com': ['https://pdiskshortener.com/', 10],
                             'mdiskshortner.link': ['https://mdiskshortner.link/', 15],
                             'rewayatcafe.com': ['https://course.rewayatcafe.com/', 7],
                             'ser2.crazyblog.in': ['https://ser3.crazyblog.in/', 12],
                             'za.uy' : ['https://za.uy/', 5],
                             'bitshorten.com': ['https://bitshorten.com/', 21]}

        shortner_dict_two = {'vearnl.in': ['https://go.urlearn.xyz/', 'https://v.modmakers.xyz/', 5],
                             'techymozo.com': ['https://push.bdnewsx.com/', 'https://veganho.co/', 8],
                             'linksxyz.in': ['https://blogshangrila.com/insurance/', 'https://cypherroot.com/', 13],
                             'short-jambo.com': ['https://short-jambo.com/', 'https://aghtas.com/how-to-create-a-forex-trading-plan/', 10],
                             'linkpays.in': ['https://m.techpoints.xyz/', 'https://www.filmypoints.in/', 10],
                             'pi-l.ink' : ['https://go.pilinks.net/', 'https://poketoonworld.com/', 5],
                             'arn4link.in': ['https://m.open2get.in/', 'https://ezeviral.com/2022/03/01/why-is-cloud-hosting-the-ideal-solution/', 3],
                             'indianshortner.in': ['https://indianshortner.com/', 'https://moddingzone.in/', 5],
                             'open2get.in': ['https://m.open2get.in/', 'https://ezeviral.com/2022/03/01/why-is-cloud-hosting-the-ideal-solution/', 3]}

        shortner_dict_three = {'du-link.in': ['https://du-link.in/', 'https://profitshort.com/', 0.5],
                               'adrinolinks.in': ['https://adrinolinks.in/', 'https://wikitraveltips.com/', 8],
                               'ez4short.com': ['https://ez4short.com/', 'https://techmody.io/', 8],
                               'shortingly.in': ['https://shortingly.in/', 'https://tech.gyanitheme.com/', 5],
                               'mdiskshortners.in': ['https://mdiskshortners.in/', 'https://www.adzz.in/', 2],
                               'mdisklink.link': ['https://mdisklink.link/', 'https://m.proappapk.com/', 2],
                               'tinyfy.in': ['https://tinyfy.in/', 'https://www.yotrickslog.tech/', 0.5],
                               'earnl.xyz': ['https://v.earnl.xyz/', 'https://link.modmakers.xyz/', 5],
                               'easysky.in': ['https://techy.veganab.co/', 'https://veganab.co/', 8],
                               'indiurl.in': ['https://file.earnash.com/', 'https://indiurl.cordtpoint.co.in/', 10],
                               'linkbnao.com': ['https://vip.linkbnao.com/', 'https://ffworld.xyz/', 2],
                               'tnshort.in': ['https://page.tnlink.in/', 'https://business.usanewstoday.club/', 8],
                               'flashlink.in': ['https://files.earnash.com/', 'https://flash1.cordtpoint.co.in/', 15],
                               'short2url.in': ['https://techyuth.xyz/blog/', 'https://blog.coin2pay.xyz/', 10],
                               'indianshortner.in': ['https://indianshortner.com/', 'https://moddingzone.in/', 5],
                               'urlsopen.': ['https://blogpost.viewboonposts.com/e998933f1f665f5e75f2d1ae0009e0063ed66f889000/', 'https://blog.textpage.xyz/', 2],
                               'xpshort.com': ['https://xpshort.com/', 'https://m.ecowas.in/', 8],
                               'push.bdnewsx.com': ['https://xpshort.com/', 'https://m.ecowas.in/', 8],
                               'techymozo.com': ['https://xpshort.com/', 'https://m.ecowas.in/', 8],
                               'moneykamalo.com': ['https://go.moneykamalo.com/', 'https://techkeshri.com/', 5]}

        return shortner_dict_one, shortner_dict_two, shortner_dict_three


def decrypt_url(code) -> str:
    '''Bitly Decrypter Function'''
    a, b = '', ''
    for i in range(0, len(code)):
        if i % 2 == 0:
            a += code[i]
        else:
            b = code[i] + b
    key = list(a + b)
    i = 0
    while i < len(key):
        if key[i].isdigit():
            for j in range(i+1, len(key)):
                if key[j].isdigit():
                    u = int(key[i]) ^ int(key[j])
                    if u < 10:
                        key[i] = str(u)
                    i = j
                    break
        i += 1
    key = ''.join(key)
    return b64decode(key)[16:-16].decode('utf-8')


def cf_bypass(url):
    "DO NOT ABUSE THIS"
    try:
        data = {"cmd": "request.get",
                "url": url,
                "maxTimeout": 60000}
        _json = post("https://cf.jmdkh.eu.org/v1", headers={"Content-Type": "application/json"}, json=data).json()
        if _json['status'] == 'ok':
            return _json['solution']["response"]
    except Exception as e:
        e
    raise DirectDownloadLinkException("ERROR: Con't bypass cloudflare")


def get_captcha_token(session, params):
    recaptcha_api = 'https://www.google.com/recaptcha/api2'
    res = session.get(f'{recaptcha_api}/anchor', params=params)
    anchor_html = HTML(res.text)
    if not (anchor_token := anchor_html.xpath('//input[@id="recaptcha-token"]/@value')):
        return
    params['c'] = anchor_token[0]
    params['reason'] = 'q'
    res = session.post(f'{recaptcha_api}/reload', params=params)
    if token := re_findall(r'"rresp","(.*?)"', res.text):
        return token[0]


def RecaptchaV3(anchor_url: str):
    url_base = 'https://www.google.com/recaptcha/'
    post_data = "v={}&reason=q&c={}&k={}&co={}"
    client = create_scraper()
    client.headers.update({'content-type': 'application/x-www-form-urlencoded'})
    matches = re_findall(r'([api2|enterprise]+)\/anchor\?(.*)', anchor_url)[0]
    url_base += matches[0] + '/'
    params = matches[1]
    res = client.get(url_base + 'anchor', params=params)
    token = re_findall(r'"recaptcha-token" value="(.*?)"', res.text)[0]
    params = dict(pair.split('=') for pair in params.split('&'))
    post_data = post_data.format(params["v"], token, params["k"], params["co"])
    res = client.post(url_base+'reload', params=f'k={params["k"]}', data=post_data)
    return re_findall(r'"rresp", "(.*?)"', res.text)[0]


def getlinks(dlc):
    '''Filecrypt Decrypter Function'''
    client = create_scraper(allow_brotli=False)
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:103.0) Gecko/20100101 Firefox/103.0',
               'Accept': 'application/json, text/javascript, */*',
               'Accept-Language': 'en-US,en;q=0.5',
               'X-Requested-With': 'XMLHttpRequest',
               'Origin': 'http://dcrypt.it',
               'Connection': 'keep-alive',
               'Referer': 'http://dcrypt.it/'}
    data = {'content': dlc}
    return client.post('http://dcrypt.it/decrypt/paste', headers=headers, data=data).json()['success']['links']
