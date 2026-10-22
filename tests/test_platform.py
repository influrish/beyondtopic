"""Smoke tests for core persistence and authentication primitives."""
import os, tempfile, unittest, re, urllib.parse
from pathlib import Path

class PlatformTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.environ['BEYONDTOPIC_DB']=str(Path(self.tmp.name)/'test.sqlite3')
        from app import db
        db.DB_PATH=Path(os.environ['BEYONDTOPIC_DB']); db.initialize()
        self.db=db
    def tearDown(self): self.tmp.cleanup()
    def test_schema_supports_content_and_categories(self):
        with self.db.connect() as conn:
            conn.execute("insert into categories(name,slug) values('Travel','travel')")
            conn.execute("insert into posts(title,slug,status,category_id) values('A guide','a-guide','published',1)")
            self.assertEqual(conn.execute("select count(*) from posts where status='published'").fetchone()[0],1)
    def test_password_hash_verifies_and_rejects_wrong_password(self):
        from app.security import password_hash, verify_password
        digest=password_hash('correct horse battery staple')
        self.assertTrue(verify_password('correct horse battery staple',digest))
        self.assertFalse(verify_password('wrong',digest))
    def test_session_signature_detects_tampering(self):
        from app.security import sign, unsign
        value=sign('editor')
        self.assertEqual(unsign(value),'editor')
        self.assertIsNone(unsign(value[:-1]+'x'))

    def test_admin_auth_and_publish_workflow(self):
        from app.security import password_hash, unsign
        from app.server import app, csrf_for
        with self.db.connect() as conn:
            conn.execute("insert into users(username,password_hash,role) values(?,?,?)",('publisher',password_hash('long-test-password-123'),'admin'))
            conn.execute("insert into authors(name,slug) values('Editor','editor')")
            conn.execute("insert into categories(name,slug) values('Travel','travel')")
        def request(path, method='GET', data=None, cookie='', content_type='application/x-www-form-urlencoded'):
            encoded=urllib.parse.urlencode(data or {}).encode()
            parsed=urllib.parse.urlsplit(path)
            env={'PATH_INFO':parsed.path,'REQUEST_METHOD':method,'QUERY_STRING':parsed.query,'HTTP_COOKIE':cookie,'CONTENT_TYPE':content_type,'CONTENT_LENGTH':str(len(encoded)),'wsgi.input':__import__('io').BytesIO(encoded),'wsgi.url_scheme':'http'}
            result={}; body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode(errors='replace')
            return result,body
        result,_=request('/admin/posts')
        self.assertEqual(result['status'],'303 See Other')
        result,body=request('/admin/login')
        login_cookie=[v for k,v in result['headers'] if k=='Set-Cookie'][0].split(';',1)[0]
        token=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
        result,_=request('/admin/login','POST',{'csrf':token,'username':'publisher','password':'long-test-password-123'},login_cookie)
        session_cookie=[v for k,v in result['headers'] if k=='Set-Cookie'][0].split(';',1)[0]
        sid=unsign(session_cookie.split('=',1)[1]); csrf=csrf_for(sid)
        payload={'csrf':csrf,'title':'A Test Journey','slug':'test-journey','excerpt':'A useful travel guide','body':'# Start here\nMake a careful plan.','category_id':'1','author_id':'1','status':'published','featured':'1'}
        result,_=request('/admin/posts/new','POST',payload,session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        payload['body']='Changed version'
        result,_=request('/admin/posts/1','POST',payload,session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        result,_=request('/admin/posts/1/restore','POST',{'csrf':csrf},session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        with self.db.connect() as conn: saved=[dict(x) for x in conn.execute('select * from posts')]
        result,body=request('/blog/test-journey')
        self.assertEqual(result['status'],'200 OK',saved); self.assertIn('A Test Journey',body); self.assertIn('Make a careful plan',body)
        result,body=request('/search?q=careful')
        self.assertEqual(result['status'],'200 OK'); self.assertIn('A Test Journey',body)
        result,_=request('/admin/pages?new=1')
        result,_=request('/admin/pages','POST',{'csrf':csrf,'title':'About Test','slug':'about-test','body':'Original page text','status':'published'},session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        result,_=request('/admin/pages?edit=1','POST',{'csrf':csrf,'title':'About Test','slug':'about-test','body':'Edited page text','status':'published'},session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        result,_=request('/admin/pages?edit=1','POST',{'csrf':csrf,'id':'1','action':'restore'},session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        result,body=request('/page/about-test')
        self.assertEqual(result['status'],'200 OK');self.assertIn('Original page text',body)
        for module in ('posts','pages','categories','tags','authors','products','affiliate-links','navigation','homepage','subscribers','seo','redirects','users','analytics','settings','activity','system','media'):
            result,_=request('/admin/'+module,cookie=session_cookie)
            self.assertEqual(result['status'],'200 OK',module)
        result,_=request('/admin/posts','POST',{'csrf':csrf,'action':'bulk','ids':'1','bulk_action':'archive'},session_cookie)
        self.assertEqual(result['status'],'303 See Other')
        with self.db.connect() as conn:self.assertEqual(conn.execute('select status from posts where id=1').fetchone()[0],'archived')

    def test_public_pages_and_csrf_cookie(self):
        from app.server import app
        from io import BytesIO
        with self.db.connect() as conn:
            conn.execute("insert into pages(title,slug,body,status) values('Privacy Policy','privacy-policy','Privacy information','published')")
            conn.execute("insert into pages(title,slug,body,status) values('Terms and Conditions','terms-and-conditions','Terms information','published')")
        result={}; env={'PATH_INFO':'/','REQUEST_METHOD':'GET','QUERY_STRING':'','HTTP_COOKIE':'','CONTENT_TYPE':'','CONTENT_LENGTH':'0','wsgi.input':BytesIO(b''),'wsgi.url_scheme':'http'}
        body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
        self.assertEqual(result['status'],'200 OK')
        self.assertIn('BeyondTopic',body)
        self.assertIn('href="/page/privacy-policy">Privacy Policy</a>',body)
        self.assertIn('href="/page/terms-and-conditions">Terms and Conditions</a>',body)
        self.assertIn('<b>Policies</b>',body)
        set_cookie=next(v for k,v in result['headers'] if k=='Set-Cookie' and 'bt_public_csrf=' in v)
        cookie=set_cookie.split(';',1)[0]
        token=__import__('re').search(r'<input type="hidden" name="csrf" value="([^"]+)"',body).group(1)
        import urllib.parse
        data=urllib.parse.urlencode({'csrf':token,'email':'reader@example.test','consent':'1'}).encode()
        env={'PATH_INFO':'/subscribe','REQUEST_METHOD':'POST','QUERY_STRING':'','HTTP_COOKIE':cookie,'CONTENT_TYPE':'application/x-www-form-urlencoded','CONTENT_LENGTH':str(len(data)),'wsgi.input':BytesIO(data),'wsgi.url_scheme':'http'}
        result={};response_body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
        self.assertEqual(result['status'],'200 OK');self.assertIn('You’re on the list',response_body)
        unsubscribe_token=__import__('re').search(r'href="/unsubscribe\?token=([^\"]+)"',response_body).group(1)
        env={'PATH_INFO':'/unsubscribe','REQUEST_METHOD':'GET','QUERY_STRING':'token='+unsubscribe_token,'HTTP_COOKIE':cookie,'CONTENT_TYPE':'','CONTENT_LENGTH':'0','wsgi.input':BytesIO(b''),'wsgi.url_scheme':'http'}
        result={};confirm=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
        self.assertEqual(result['status'],'200 OK');self.assertIn('Confirm unsubscribe',confirm)
        unsubscribe_csrf=__import__('re').search(r'name="csrf" value="([^\"]+)"',confirm).group(1)
        post_token=__import__('re').search(r'name="token" value="([^\"]+)"',confirm).group(1)
        post=urllib.parse.urlencode({'csrf':unsubscribe_csrf,'token':post_token}).encode()
        env={'PATH_INFO':'/unsubscribe','REQUEST_METHOD':'POST','QUERY_STRING':'','HTTP_COOKIE':cookie,'CONTENT_TYPE':'application/x-www-form-urlencoded','CONTENT_LENGTH':str(len(post)),'wsgi.input':BytesIO(post),'wsgi.url_scheme':'http'}
        result={};done=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
        self.assertEqual(result['status'],'200 OK');self.assertIn('unsubscribed',done.lower())
        with self.db.connect() as conn:self.assertEqual(conn.execute("select status from subscribers where email='reader@example.test'").fetchone()[0],'unsubscribed')

    def test_due_scheduled_content_and_redirect_safety(self):
        from app.server import process_due, redirect_loops, safe_external
        with self.db.connect() as conn:
            conn.execute("insert into categories(name,slug) values('Travel','travel')")
            conn.execute("insert into posts(title,slug,status,category_id,scheduled_at) values('Scheduled guide','scheduled-guide','scheduled',1,'2000-01-01 10:00:00')")
            conn.execute("insert into redirects(source,destination,code,active) values('/old','/new',301,1)")
            conn.commit(); process_due(conn)
            self.assertEqual(conn.execute("select status from posts where slug='scheduled-guide'").fetchone()[0],'published')
            self.assertTrue(redirect_loops(conn,'/new','/old'))
        self.assertTrue(safe_external('https://merchant.example/item'))
        self.assertFalse(safe_external('javascript:alert(1)'))

    def test_schedule_timezone_round_trip(self):
        from app.server import normalize_schedule, display_schedule
        self.assertEqual(normalize_schedule('2026-10-09T12:00'),'2026-10-09 06:30:00')
        self.assertEqual(display_schedule('2026-10-09 06:30:00'),'2026-10-09T12:00')

    def test_author_role_is_limited_to_editorial_content(self):
        from app.server import app
        from app.security import sign, session_stamp
        from io import BytesIO
        with self.db.connect() as conn:
            conn.execute("insert into authors(name,slug) values('Writer','writer')")
            conn.execute("insert into users(username,password_hash,role,author_id) values('writer',?,'author',1)",("unused",))
            uid=conn.execute("select id from users where username='writer'").fetchone()[0]
        token=f'{uid}:9999999999:{session_stamp("unused")}'
        env={'PATH_INFO':'/admin/settings','REQUEST_METHOD':'GET','QUERY_STRING':'','HTTP_COOKIE':'bt_session='+sign(token),'CONTENT_TYPE':'','CONTENT_LENGTH':'0','wsgi.input':BytesIO(b''),'wsgi.url_scheme':'http'}
        result={};b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers)))
        self.assertEqual(result['status'],'403 Forbidden')

    def test_editorial_homepage_and_article_use_database_content(self):
        from app.server import app
        from io import BytesIO
        with self.db.connect() as conn:
            conn.execute("insert into authors(name,slug,bio) values('BeyondTopic Editor','editor','Thoughtful editorial guides.')")
            conn.execute("insert into categories(name,slug,description) values('Fashion','fashion','Personal style and considered wardrobes.')")
            conn.execute("insert into posts(title,slug,excerpt,body,status,author_id,category_id,featured,is_sample,featured_image,image_alt,published_at) values(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",('A Considered Wardrobe','considered-wardrobe','A useful wardrobe starts with the way you actually live.','# Begin with what you wear\nNotice what earns its place.','published',1,1,1,1,'https://images.unsplash.com/photo-1483985988355-763728e1935b','A considered wardrobe'))
        def get(path):
            url=urllib.parse.urlsplit(path);result={}
            env={'PATH_INFO':url.path,'REQUEST_METHOD':'GET','QUERY_STRING':url.query,'HTTP_HOST':'localhost','CONTENT_LENGTH':'0','wsgi.input':BytesIO(b''),'wsgi.url_scheme':'http'}
            body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
            return result,body
        result,home=get('/')
        self.assertEqual(result['status'],'200 OK');self.assertIn('BeyondTopic',home)
        self.assertIn('AN INDEPENDENT JOURNAL',home);self.assertIn('hero-image',home)
        self.assertIn('sample-badge',home);self.assertIn('name="q"',home);self.assertIn('<details class="mobile-menu">',home)
        self.assertIn('id="main-content"',home);self.assertIn('/static/site.css?v=',home)
        import json
        home_schemas=[json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',home)]
        self.assertTrue(any(x.get('@type')=='WebSite' for x in home_schemas))
        self.assertTrue(any(x.get('publisher',{}).get('@type')=='Organization' for x in home_schemas))
        self.assertTrue(any('/search?q={search_term_string}' in x.get('potentialAction',{}).get('target','') for x in home_schemas))
        result,category=get('/category/fashion')
        self.assertEqual(result['status'],'200 OK');self.assertIn('Personal style and considered wardrobes.',category)
        result,article=get('/blog/considered-wardrobe')
        self.assertEqual(result['status'],'200 OK');self.assertIn('article-deck',article);self.assertIn('editable starter content',article)
        article_schemas=[json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>',article)]
        self.assertTrue(any(x.get('@type')=='Article' for x in article_schemas))
        result,script=get('/static/editor.js')
        self.assertEqual(result['status'],'200 OK');self.assertIn('preview-toggle',script)

    def test_specialist_roles_are_limited_to_their_modules(self):
        from app.server import app
        from app.security import sign
        from io import BytesIO
        with self.db.connect() as conn:
            conn.execute("insert into authors(name,slug) values('Writer','writer')")
            for role,name in [('seo_manager','seo_user'),('affiliate_manager','affiliate_user'),('contributor','contributor_user')]:
                conn.execute('insert into users(username,password_hash,role,author_id) values(?,?,?,?)',(name,'unused',role,1 if role=='contributor' else None))
            conn.execute('update users set author_id=1 where username=?',('contributor_user',))
            conn.commit()
        from app.security import session_stamp
        def request(username,path):
            with self.db.connect() as conn:user=conn.execute('select id from users where username=?',(username,)).fetchone()
            cookie=sign(f'{user["id"]}:9999999999:{session_stamp("unused")}')
            result={};env={'PATH_INFO':path,'REQUEST_METHOD':'GET','QUERY_STRING':'','HTTP_COOKIE':'bt_session='+cookie,'CONTENT_TYPE':'','CONTENT_LENGTH':'0','wsgi.input':BytesIO(b''),'wsgi.url_scheme':'http'}
            b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers)))
            return result['status']
        self.assertEqual(request('seo_user','/admin/seo'),'200 OK')
        self.assertEqual(request('seo_user','/admin/products'),'403 Forbidden')
        self.assertEqual(request('affiliate_user','/admin/products'),'200 OK')
        self.assertEqual(request('affiliate_user','/admin/settings'),'403 Forbidden')
        self.assertEqual(request('contributor_user','/admin/posts'),'200 OK')
        self.assertEqual(request('contributor_user','/admin/users'),'403 Forbidden')

    def test_homepage_sections_can_be_added_reordered_and_disabled(self):
        from app.server import app, csrf_for
        from app.security import sign, password_hash, session_stamp
        from io import BytesIO
        hashed=password_hash('test-password-long-enough')
        with self.db.connect() as conn:
            conn.execute("insert into users(username,password_hash,role) values('publisher',?,'admin')",(hashed,))
            conn.execute("insert into categories(name,slug) values('Fashion','fashion')")
            conn.execute("insert into categories(name,slug) values('Travel','travel')")
            uid=conn.execute("select id from users where username='publisher'").fetchone()[0]
        token=f'{uid}:9999999999:{session_stamp(hashed)}'
        cookie='bt_session='+sign(token);csrf=csrf_for(token)
        def request(path,method='GET',data=None):
            encoded=urllib.parse.urlencode(data or {}).encode();url=urllib.parse.urlsplit(path);result={}
            env={'PATH_INFO':url.path,'REQUEST_METHOD':method,'QUERY_STRING':url.query,'HTTP_COOKIE':cookie,'CONTENT_TYPE':'application/x-www-form-urlencoded','CONTENT_LENGTH':str(len(encoded)),'wsgi.input':BytesIO(encoded),'wsgi.url_scheme':'http'}
            body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
            return result,body
        result,_=request('/admin/homepage','POST',{'csrf':csrf,'title':'Fashion edit','section_type':'category:fashion','position':'0','enabled':'1'})
        self.assertEqual(result['status'],'303 See Other')
        result,_=request('/admin/homepage','POST',{'csrf':csrf,'title':'Latest stories','section_type':'latest','position':'0','enabled':'1'})
        self.assertEqual(result['status'],'303 See Other')
        with self.db.connect() as conn:ids=[x['id'] for x in conn.execute('select id from homepage_sections order by position,id')]
        request('/admin/homepage','POST',{'csrf':csrf,'id':str(ids[1]),'action':'move_up'})
        with self.db.connect() as conn:self.assertEqual(conn.execute('select title from homepage_sections order by position,id limit 1').fetchone()[0],'Latest stories')
        request('/admin/homepage','POST',{'csrf':csrf,'id':str(ids[0]),'action':'toggle'})
        result,home=request('/')
        self.assertEqual(result['status'],'200 OK');self.assertNotIn('class="category-section"',home)

    def test_author_profile_media_photo_shows_on_public_byline(self):
        from app.server import app, csrf_for
        from app.security import sign, password_hash, session_stamp
        from io import BytesIO
        hashed=password_hash('test-password-long-enough')
        with self.db.connect() as conn:
            conn.execute("insert into users(username,password_hash,role) values('publisher',?,'admin')",(hashed,))
            conn.execute("insert into authors(name,slug,bio) values('Writer','writer','A thoughtful writer.')")
            conn.execute("insert into categories(name,slug) values('Travel','travel')")
            conn.execute("insert into media(filename,alt,mime_type,size) values('portrait.jpg','Writer portrait','image/jpeg',100)")
            uid=conn.execute("select id from users where username='publisher'").fetchone()[0]
        sid=f'{uid}:9999999999:{session_stamp(hashed)}';cookie='bt_session='+sign(sid);csrf=csrf_for(sid)
        def request(path,method='GET',data=None,authenticated=False):
            encoded=urllib.parse.urlencode(data or {}).encode();url=urllib.parse.urlsplit(path);result={}
            env={'PATH_INFO':url.path,'REQUEST_METHOD':method,'QUERY_STRING':url.query,'HTTP_COOKIE':cookie if authenticated else '', 'CONTENT_TYPE':'application/x-www-form-urlencoded','CONTENT_LENGTH':str(len(encoded)),'wsgi.input':BytesIO(encoded),'wsgi.url_scheme':'http'}
            body=b''.join(app(env,lambda status,headers:result.update(status=status,headers=headers))).decode()
            return result,body
        result,_=request('/admin/authors','POST',{'csrf':csrf,'id':'1','name':'Writer','slug':'writer','job_title':'Travel Writer','bio':'A thoughtful writer.','photo_media':'/media/portrait.jpg','photo_url':'','email':'','social_links':''},True)
        self.assertEqual(result['status'],'303 See Other')
        with self.db.connect() as conn:
            conn.execute("insert into posts(title,slug,excerpt,body,status,author_id,category_id,published_at) values('A Travel Story','travel-story','A useful guide.','A useful plan.','published',1,1,CURRENT_TIMESTAMP)")
        result,profile=request('/author/writer')
        self.assertEqual(result['status'],'200 OK');self.assertIn('class="author-photo" src="/media/portrait.jpg"',profile)
        result,story=request('/blog/travel-story')
        self.assertEqual(result['status'],'200 OK');self.assertIn('class="byline-avatar" src="/media/portrait.jpg"',story)

if __name__=='__main__': unittest.main()
