"""BeyondTopic's dependency-free WSGI publishing application."""
import cgi, html, json, mimetypes, os, random, re, secrets, threading, time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from http import cookies
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, quote, urlencode
from wsgiref.simple_server import make_server
from . import db as database
from .security import sign, unsign, password_hash, verify_password, fingerprint

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = Path(os.environ.get('BEYONDTOPIC_MEDIA_DIR', '/tmp/beyondtopic-media' if os.environ.get('VERCEL') else ROOT / 'data' / 'media'))
STATUS = ['draft','pending_review','scheduled','published','archived','trashed']
ASSET_VERSION = '20261009.20'
_site_data_ready = False
_site_data_lock = threading.Lock()

def esc(v): return html.escape(str(v if v is not None else ''), quote=True)
def slugify(v): return re.sub(r'[^a-z0-9]+','-',str(v or '').lower()).strip('-') or secrets.token_hex(4)
def normalize_schedule(value):
    if not value:return None
    try: parsed=datetime.fromisoformat(value.strip().replace(' ','T'))
    except ValueError: raise ValueError('Enter a valid scheduled date and time.')
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=ZoneInfo(os.environ.get('BEYONDTOPIC_TIMEZONE','Asia/Kolkata')))
    return parsed.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
def display_schedule(value):
    if not value:return ''
    try:
        parsed=datetime.fromisoformat(value.replace(' ','T'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(os.environ.get('BEYONDTOPIC_TIMEZONE','Asia/Kolkata'))).strftime('%Y-%m-%dT%H:%M')
    except (ValueError,KeyError):return value.replace(' ','T')[:16]
def csrf_for(sid): return sign('csrf:'+sid)
def field(name,label,kind='text',value='',required=False,options=None):
    req=' required' if required else ''
    if kind=='textarea': control=f'<textarea name="{esc(name)}" rows="6"{req}>{esc(value)}</textarea>'
    elif kind=='select':
        opts=''.join(f'<option value="{esc(v)}" {"selected" if str(value)==str(v) else ""}>{esc(l)}</option>' for v,l in options or [])
        control=f'<select name="{esc(name)}"{req}>{opts}</select>'
    elif kind=='checkbox': control=f'<input type="checkbox" name="{esc(name)}" value="1" {"checked" if value else ""}>'
    else: control=f'<input type="{esc(kind)}" name="{esc(name)}" value="{esc(value)}"{req}>'
    return f'<label>{esc(label)}{control}</label>'

def layout(title, body, admin=False, description='BeyondTopic — thoughtful stories for curious lives.', csrf='', public_links=None, site_title='BeyondTopic', tagline='Explore More. Discover Beyond.', canonical='', noindex=False, social_image='', footer_categories=None, footer_pages=None, admin_role=None, site_url='', contact_email=''):
    if admin:
        links=['Dashboard:/admin','Stories:/admin/posts','Pages:/admin/pages','Categories:/admin/categories','Tags:/admin/tags','Authors:/admin/authors','Media:/admin/media','Products:/admin/products','Affiliate links:/admin/affiliate-links','Advertising:/admin/advertising','Navigation:/admin/navigation','Homepage:/admin/homepage','Subscribers:/admin/subscribers','SEO:/admin/seo','Redirects:/admin/redirects','Users:/admin/users','Analytics:/admin/analytics','Settings:/admin/settings','Activity:/admin/activity','System:/admin/system']
        if admin_role in ('author','contributor'): links=['Dashboard:/admin','Stories:/admin/posts','Media:/admin/media']
        elif admin_role=='editor': links=[x for x in links if x.split(':',1)[1] not in ('/admin/users','/admin/settings','/admin/seo','/admin/system')]
        elif admin_role=='seo_manager':links=['SEO settings:/admin/seo','Redirects:/admin/redirects']
        elif admin_role=='affiliate_manager':links=['Products:/admin/products','Affiliate links:/admin/affiliate-links']
        nav='<a class="brand" href="/admin">BeyondTopic <small>Studio</small></a><nav>'+''.join(f'<a href="{u}">{esc(label)}</a>' for label,u in (x.split(':',1) for x in links))+'<a href="/">View website</a><form class="logout" method="post" action="/admin/logout"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><button>Log out</button></form></nav>'
    else:
        links=public_links or [('Stories','/blog'),('Fashion','/category/fashion'),('Travel','/category/travel'),('Wellness','/category/wellness'),('Search','/search')]
        items=''.join(f'<a href="{esc(u)}">{esc(label)}</a>' for label,u in links)
        nav=f'<nav class="main-nav"><a class="brand" href="/">{esc(site_title)}<small>{esc(tagline)}</small></a><div class="nav-links">{items}</div><form class="nav-search" action="/search" method="get" role="search"><label class="sr-only" for="site-search">Search BeyondTopic</label><input id="site-search" type="search" name="q" placeholder="Search stories" aria-label="Search stories"><button aria-label="Submit search">⌕</button></form><details class="mobile-menu"><summary aria-label="Open navigation">Explore</summary><div>{items}</div></details></nav>'
    canonical_tag=f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''
    robot_tag='<meta name="robots" content="noindex,nofollow">' if noindex else ''
    image_tag=f'<meta property="og:image" content="{esc(social_image)}"><meta name="twitter:image" content="{esc(social_image)}">' if social_image else ''
    schema_base=(site_url or os.environ.get('BEYONDTOPIC_URL','http://localhost:8000')).rstrip('/')
    site_schema=json.dumps({'@context':'https://schema.org','@type':'WebSite','name':site_title,'url':schema_base,'description':description,'publisher':{'@type':'Organization','name':site_title,'url':schema_base},'potentialAction':{'@type':'SearchAction','target':schema_base+'/search?q={search_term_string}','query-input':'required name=search_term_string'}}).replace('<','\\u003c')
    schema_tag='' if admin else f'<script type="application/ld+json">{site_schema}</script>'
    cats=''.join(f'<a href="/category/{quote(c["slug"])}">{esc(c["name"])}</a>' for c in (footer_categories or []))
    legal_slugs={'privacy-policy','terms-and-conditions','cookie-policy','affiliate-disclosure','editorial-policy'}
    about_pages=''.join(f'<a href="/page/{quote(p["slug"])}">{esc(p["title"])}</a>' for p in (footer_pages or []) if p['slug'] not in legal_slugs)
    legal_pages=''.join(f'<a href="/page/{quote(p["slug"])}">{esc(p["title"])}</a>' for p in (footer_pages or []) if p['slug'] in legal_slugs)
    contact=f'<a class="footer-contact" href="mailto:{esc(contact_email)}">{esc(contact_email)}</a>' if contact_email else ''
    footer=f'<footer class="site-footer"><div class="footer-brand"><a href="/">{esc(site_title)}</a><p>{esc(tagline)}</p><span>An independent journal for curious lives.</span>{contact}</div><div class="footer-col"><b>Explore</b>{cats}<a href="/blog">All stories</a></div><div class="footer-col"><b>About</b>{about_pages}<a href="/admin/login">Publisher sign in</a></div><div class="footer-col"><b>Policies</b>{legal_pages}</div><div class="footer-bottom">© {datetime.now().year} {esc(site_title)} <span>Thoughtfully made for curious lives.</span></div></footer>'
    script=f'<script src="/static/editor.js?v={ASSET_VERSION}" defer></script>'
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f8f7f3"><meta name="description" content="{esc(description)}">{canonical_tag}{robot_tag}<meta property="og:site_name" content="{esc(site_title)}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta name="twitter:card" content="summary_large_image">{image_tag}{schema_tag}<title>{esc(title)} · {esc(site_title)}</title><link rel="icon" href="/static/favicon.svg?v={ASSET_VERSION}" type="image/svg+xml"><link rel="stylesheet" href="/static/site.css?v={ASSET_VERSION}"></head><body class="{"admin" if admin else "public"}"><a class="skip-link" href="#main-content">Skip to content</a><header>{nav}</header><main id="main-content">{body}</main>{footer}{script}</body></html>'

def response(start, body='', status='200 OK', headers=None):
    h=[('Content-Type','text/html; charset=utf-8'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','strict-origin-when-cross-origin'),('X-Frame-Options','DENY'),('Cache-Control','no-store')]
    if headers: h.extend(headers)
    start(status,h)
    return [body.encode() if isinstance(body,str) else body]

def render(start,title,content,admin=False,status='200 OK',description=None,csrf='',canonical='',noindex=False,social_image=''):
    return response(start,layout(title,content,admin,description or 'BeyondTopic — thoughtful stories for curious lives.',csrf,canonical=canonical,noindex=noindex,social_image=social_image),status)

def app(environ,start_response):
    global _site_data_ready
    if os.environ.get('VERCEL') and not _site_data_ready:
        with _site_data_lock:
            if not _site_data_ready:
                initialize_site_data()
                _site_data_ready=True
    path=decode_path(environ.get('PATH_INFO','/')); method=environ.get('REQUEST_METHOD','GET').upper(); query=parse_qs(environ.get('QUERY_STRING',''))
    jar=cookies.SimpleCookie(environ.get('HTTP_COOKIE','')); db=database.connect(); set_cookie=[]
    public_token=unsign(jar['bt_public_csrf'].value) if 'bt_public_csrf' in jar else None
    if not public_token:
        public_token=secrets.token_urlsafe(24)
        set_cookie.append(('Set-Cookie',f'bt_public_csrf={sign(public_token)}; SameSite=Lax; Path=/; Max-Age=86400'))
    sid=unsign(jar['bt_session'].value) if 'bt_session' in jar else None
    user=None
    if sid:
        found=db.execute('select u.*,s.expires_at from sessions s join users u on u.id=s.user_id where s.id=?',(sid,)).fetchone()
        if found and found['expires_at']>int(time.time()): user=found
        else: sid=None
    csrf=csrf_for(sid) if sid else ''
    def go(url,status='303 See Other',headers=None): return response(start_response,'',status,[('Location',url)]+(headers or []))
    def page(title,body,admin=bool(user),status='200 OK',description=None,canonical='',noindex=False,social_image=''):
        headers=list(set_cookie)
        set_cookie.clear()
        links=[(x['label'],x['url']) for x in db.execute('select label,url from menu_items where active=1 order by position,id')]
        if not links: links=[('Stories','/blog')]+[(x['name'],'/category/'+x['slug']) for x in db.execute('select name,slug from categories where parent_id is null and active=1 order by name')]
        links.append(('Search','/search'))
        footer_categories=db.execute('select name,slug from categories where parent_id is null and active=1 order by name').fetchall()
        footer_pages=db.execute("select title,slug from pages where status='published' order by title").fetchall()
        site={x['key'].split('.',1)[1]:x['value'] for x in db.execute("select * from settings where key like 'site.%'")}
        seo_base=db.execute("select value from settings where key='seo.canonical_base'").fetchone()
        site_url=(seo_base['value'].rstrip('/') if seo_base and seo_base['value'] else os.environ.get('BEYONDTOPIC_URL','https://beyondtopic.vercel.app' if os.environ.get('VERCEL') else 'http://localhost:8000').rstrip('/'))
        return response(start_response,layout(title,body,admin,description or site.get('tagline','BeyondTopic — thoughtful stories for curious lives.'),csrf,links,site.get('site_title',site.get('title','BeyondTopic')),site.get('tagline','Explore More. Discover Beyond.'),canonical,noindex,social_image,footer_categories,footer_pages,user['role'] if admin and user else None,site_url,site.get('contact_email','')),status,headers)
    def values():
        typ=environ.get('CONTENT_TYPE','')
        if typ.startswith('multipart/form-data'):
            if int(environ.get('CONTENT_LENGTH') or 0)>5_500_000:raise ValueError('Multipart uploads are limited to 5 MB plus form data.')
            environ['QUERY_STRING']=environ.get('QUERY_STRING','')
            fs=cgi.FieldStorage(fp=environ['wsgi.input'],environ=environ,keep_blank_values=True)
            return fs
        length=min(int(environ.get('CONTENT_LENGTH') or 0),2_100_000)
        return {k:v[-1] for k,v in parse_qs(environ['wsgi.input'].read(length).decode(errors='replace'),keep_blank_values=True).items()}
    def valid_csrf(f, token=None):
        got=f.getfirst('csrf','') if isinstance(f,cgi.FieldStorage) else f.get('csrf','')
        return bool(token and secrets.compare_digest(got,token))
    def audit(action,detail=''):
        db.execute('insert into audit_logs(username,action,detail) values(?,?,?)',(user['username'] if user else 'system',action,detail[:300])); db.commit()
    try:
        if path=='/static/site.css': return static_response(start_response,ROOT/'app'/'static'/'site.css','text/css; charset=utf-8')
        if path=='/static/editor.js': return static_response(start_response,ROOT/'app'/'static'/'editor.js','text/javascript; charset=utf-8')
        if path=='/static/favicon.svg': return static_response(start_response,ROOT/'app'/'static'/'favicon.svg','image/svg+xml')
        if path.startswith('/assets/'): return static_response(start_response,ROOT/'app'/'static'/'images'/Path(path).name,'image/jpeg')
        if path=='/favicon.ico': return response(start_response,b'','204 No Content',[('Content-Type','image/x-icon')])
        if path.startswith('/media/'): return media_response(start_response,path)
        if path=='/admin/login':
            token=secrets.token_urlsafe(24)
            if method=='POST':
                f=values(); cookie=unsign(jar['bt_login_csrf'].value) if 'bt_login_csrf' in jar else None
                if not cookie or not valid_csrf(f,cookie): return login_page(start_response,'Invalid form token. Reload and try again.','403 Forbidden')
                addr=fingerprint(environ.get('REMOTE_ADDR','unknown'))
                attempts=db.execute("select count(*) from auth_attempts where fingerprint=? and succeeded=0 and created_at>=datetime('now','-15 minutes')",(addr,)).fetchone()[0]
                if attempts>=8:return login_page(start_response,'Too many sign-in attempts. Wait 15 minutes before trying again.','429 Too Many Requests',cookie)
                row=db.execute('select * from users where username=?',(f.get('username',''),)).fetchone()
                db.execute('insert into auth_attempts(fingerprint,succeeded) values(?,?)',(addr,int(bool(row and verify_password(f.get('password',''),row['password_hash'])))));db.commit()
                if row and verify_password(f.get('password',''),row['password_hash']):
                    newsid=secrets.token_urlsafe(32); expiry=int(time.time())+8*3600
                    db.execute('insert into sessions(id,user_id,expires_at) values(?,?,?)',(newsid,row['id'],expiry)); db.commit()
                    return go('/admin',headers=[('Set-Cookie',f'bt_session={sign(newsid)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800; Secure' if environ.get('wsgi.url_scheme')=='https' else f'bt_session={sign(newsid)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800')])
                return login_page(start_response,'Login was not accepted.','401 Unauthorized',cookie)
            login_cookie=sign(token)
            return response(start_response,layout('Publisher login','<h1>Publisher login</h1><p>Sign in to manage BeyondTopic.</p>'+login_form(token),False),headers=[('Set-Cookie',f'bt_login_csrf={login_cookie}; SameSite=Lax; Path=/; Max-Age=900')])
        if path.startswith('/admin'):
            if not user: return go('/admin/login')
            if method=='POST':
                f=values()
                if not valid_csrf(f,csrf): return page('Invalid form token','<h1>Form expired</h1><p>Reload the page before submitting again.</p>',True,'403 Forbidden')
            else: f={}
            if path=='/admin/logout' and method=='POST':
                db.execute('delete from sessions where id=?',(sid,)); db.commit()
                return go('/admin/login',headers=[('Set-Cookie','bt_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax')])
            if user['role'] not in ('admin','editor','author','contributor','seo_manager','affiliate_manager'): return page('Access denied','<h1>Access denied</h1>',True,'403 Forbidden')
            if user['role'] in ('author','contributor') and not (path.startswith('/admin/posts') or path=='/admin/media' or path=='/admin/logout'):
                return page('Access denied','<h1>Your role can manage assigned stories and media only.</h1>',True,'403 Forbidden')
            if user['role']=='editor' and path in ('/admin/users','/admin/settings','/admin/seo','/admin/system'):
                return page('Access denied','<h1>Only administrators can manage users or site-wide settings.</h1>',True,'403 Forbidden')
            if user['role']=='seo_manager' and path not in ('/admin','/admin/','/admin/seo','/admin/redirects','/admin/logout'):
                return page('Access denied','<h1>Your role can manage SEO settings and redirects only.</h1>',True,'403 Forbidden')
            if user['role']=='affiliate_manager' and path not in ('/admin','/admin/','/admin/products','/admin/affiliate-links','/admin/logout'):
                return page('Access denied','<h1>Your role can manage affiliate products and links only.</h1>',True,'403 Forbidden')
            if path in ('/admin','/admin/'):
                if user['role'] in ('author','contributor'):
                    authored=[('Published stories',"posts where status='published' and author_id="+str(int(user['author_id'] or -1))),('Drafts',"posts where status='draft' and author_id="+str(int(user['author_id'] or -1))),('Scheduled',"posts where status='scheduled' and author_id="+str(int(user['author_id'] or -1)))]
                    cards=''.join(f'<div class="stat"><b>{db.execute("select count(*) from "+expr).fetchone()[0]}</b><span>{esc(label)}</span></div>' for label,expr in authored)
                    rows=db.execute('select p.id,p.title,p.slug,p.status,p.updated_at,c.name category from posts p left join categories c on c.id=p.category_id where p.author_id=? order by p.updated_at desc limit 8',(user['author_id'] or -1,)).fetchall()
                    listing=table(['Your stories','Category','Status','Updated'],[[f'<a href="/admin/posts/{x["id"]}">{esc(x["title"])}</a>',esc(x['category']),esc(x['status']),esc(x['updated_at'])] for x in rows])
                    return page('Your workspace',f'<p class="eyebrow">AUTHOR WORKSPACE</p><h1>Your stories</h1><div class="stats">{cards}</div><p><a class="button" href="/admin/posts/new">Write a story</a></p>{listing}',True)
                if user['role']=='seo_manager':
                    incomplete=db.execute("select count(*) from posts where status='published' and (trim(seo_title)='' or trim(meta_description)='')").fetchone()[0]
                    return page('SEO workspace',f'<p class="eyebrow">SEARCH PRESENCE</p><h1>SEO workspace</h1><div class="stats"><div class="stat"><b>{incomplete}</b><span>Published stories needing metadata</span></div><div class="stat"><b>{db.execute("select count(*) from redirects where active=1").fetchone()[0]}</b><span>Active redirects</span></div></div><p><a class="button" href="/admin/seo">SEO settings</a> <a class="button secondary" href="/admin/redirects">Manage redirects</a></p>',True)
                if user['role']=='affiliate_manager':
                    products=db.execute('select count(*) from products where active=1').fetchone()[0];links=db.execute('select count(*) from affiliate_links where active=1').fetchone()[0]
                    return page('Affiliate workspace',f'<p class="eyebrow">COMMERCE MANAGEMENT</p><h1>Affiliate workspace</h1><div class="stats"><div class="stat"><b>{products}</b><span>Active products</span></div><div class="stat"><b>{links}</b><span>Active links</span></div></div><p><a class="button" href="/admin/products">Manage products</a> <a class="button secondary" href="/admin/affiliate-links">Manage links</a></p>',True)
                stats=[('Published stories',"posts where status='published'"),('Drafts',"posts where status='draft'"),('Scheduled',"posts where status='scheduled'"),('Pages','pages'),('Categories','categories'),('Authors','authors'),('Affiliate links','affiliate_links'),('Active subscribers',"subscribers where status='subscribed'")]
                cards=''.join(f'<div class="stat"><b>{db.execute("select count(*) from "+expr).fetchone()[0]}</b><span>{esc(label)}</span></div>' for label,expr in stats)
                rows=db.execute('select p.id,p.title,p.slug,p.status,p.updated_at,c.name category from posts p left join categories c on c.id=p.category_id order by p.updated_at desc limit 8').fetchall()
                listing=table(['Title','Category','Status','Updated'],[[f'<a href="/admin/posts/{x["id"]}">{esc(x["title"])}</a>',esc(x['category']),esc(x['status']),esc(x['updated_at'])] for x in rows])
                return page('Dashboard',f'<h1>Studio dashboard</h1><div class="stats">{cards}</div><p class="actions"><a class="button" href="/admin/posts/new">Create post</a> <a class="button secondary" href="/admin/pages?new=1">Create page</a> <a class="button secondary" href="/admin/media">Upload media</a></p><h2>Recent content</h2>{listing}<h2>Recent activity</h2>{audit_view(db)}',True)
            if path=='/admin/posts' or path=='/admin/posts/': return posts_list(db,page,query,user,method,f,csrf,go,audit)
            if path=='/admin/posts/new' or re.fullmatch(r'/admin/posts/\d+(?:/(?:restore|delete))?',path): return edit_post(db,path,method,f,user,csrf,page,go,audit)
            if path=='/admin/categories' or re.fullmatch(r'/admin/categories/\d+',path): return manage_categories(db,path,method,f,csrf,page,go,audit)
            if path=='/admin/pages': return manage_pages(db,method,f,query,user,csrf,page,go,audit)
            if path=='/admin/tags': return manage_tags(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/authors': return manage_authors(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/products': return manage_products(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/affiliate-links': return manage_affiliate(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/redirects': return manage_redirects(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/navigation': return manage_navigation(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/homepage': return manage_homepage(db,method,f,query,csrf,page,go,audit)
            if path=='/admin/advertising': return manage_advertising(db,method,f,csrf,page,go,audit)
            if path=='/admin/media': return manage_media(db,environ,method,f,query,csrf,page,go,audit)
            if path=='/admin/subscribers/export.csv':
                import csv,io
                output=io.StringIO();writer=csv.writer(output);writer.writerow(['email','status','consent_at','created_at'])
                writer.writerows([tuple(x) for x in db.execute('select email,status,consent_at,created_at from subscribers order by created_at desc')])
                return response(start_response,output.getvalue(),'200 OK',[('Content-Type','text/csv; charset=utf-8'),('Content-Disposition','attachment; filename="beyondtopic-subscribers.csv"')])
            if path=='/admin/subscribers': return admin_subscribers(db,page)
            if path=='/admin/activity': return page('Activity log','<h1>Activity log</h1>'+audit_view(db,100),True)
            if path=='/admin/analytics': return page('Analytics','<h1>Analytics</h1><p>Analytics provider is not configured. No visitor metrics are being reported.</p>',True)
            if path=='/admin/seo': return manage_settings(db,method,f,csrf,page,go,audit,'seo')
            if path=='/admin/settings': return manage_settings(db,method,f,csrf,page,go,audit,'site')
            if path=='/admin/users':
                if user['role']!='admin': return page('Access denied','<h1>Only administrators can manage users.</h1>',True,'403 Forbidden')
                return manage_users(db,method,f,user,csrf,page,go,audit)
            if path=='/admin/system': return page('System status',f'<h1>System status</h1><ul><li>Python {esc(os.sys.version.split()[0])}</li><li>SQLite {esc(db.execute("select sqlite_version()").fetchone()[0])}</li><li>Database path: {esc(database.DB_PATH)}</li><li>File storage: local filesystem</li><li>Background publishing: active within this server process</li></ul><p>Back up the database and media folder together.</p>',True)
            return page('Admin module not found','<h1>Admin module not found</h1>',True,'404 Not Found')
        if path=='/' or path=='/blog':
            process_due(db)
            term=query.get('q',[''])[0].strip()
            where="where p.status='published'"; args=[]
            if term: where+=" and (p.title like ? or p.excerpt like ? or p.body like ?)"; args += ['%'+term+'%']*3
            total=db.execute(f'select count(*) from posts p {where}',args).fetchone()[0]; offset=max(0,(int(query.get('page',['1'])[0] or 1)-1))*16
            posts=db.execute(f'select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id {where} order by p.featured desc,p.published_at desc limit 16 offset ?',args+[offset]).fetchall()
            hero=next((x for x in posts if x['featured']),posts[0] if posts else None)
            hero_stories=[]
            if path=='/' and hero:
                candidates=db.execute(f'select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id {where} order by p.featured desc,p.published_at desc,p.id desc limit 60',args).fetchall()
                hero=next((x for x in candidates if x['featured']),candidates[0] if candidates else None)
                hero_stories=[hero]
                same_category=next((x for x in candidates if x['id']!=hero['id'] and x['category_id']==hero['category_id']),None)
                if same_category:hero_stories.append(same_category)
                seen_categories={x['category_id'] for x in hero_stories}
                for candidate in candidates:
                    if len(hero_stories)>=5:break
                    if candidate['id'] not in {x['id'] for x in hero_stories} and candidate['category_id'] not in seen_categories:
                        hero_stories.append(candidate);seen_categories.add(candidate['category_id'])
                for candidate in candidates:
                    if len(hero_stories)>=5:break
                    if candidate['id'] not in {x['id'] for x in hero_stories}:hero_stories.append(candidate)
                hero_ids=[x['id'] for x in hero_stories]
                marks=','.join('?' for _ in hero_ids)
                remaining=db.execute(f'select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.status="published" and p.id not in ({marks}) order by p.featured desc,p.published_at desc,p.id desc limit 8 offset ?',hero_ids+[offset]).fetchall()
                hero_html=story_hero_carousel(hero_stories)
                total=max(0,total-len(hero_ids))
            else:
                hero_html=story_hero(hero) if hero else '<section class="hero"><p class="eyebrow">INDEPENDENT EDITORIAL</p><h1>Explore more.<br>Discover beyond.</h1><p>Thoughtful stories and useful guides for curious lives.</p><a href="/blog">Explore our stories →</a></section>'
                remaining=[x for x in posts if not hero or x['id']!=hero['id']]
            cats=db.execute('select * from categories where parent_id is null and active=1 order by name').fetchall()
            configured_sections=db.execute('select * from homepage_sections order by position,id').fetchall()
            active_sections=[section for section in configured_sections if section['enabled']]
            listing='<div class="grid">'+''.join(article_card(x) for x in remaining)+'</div>' if remaining else '<p class="empty-state">New stories are on the way.</p>'
            if configured_sections:
                sections=''
                for section in active_sections:
                    if section['section_type']=='latest' and remaining:sections+=f'<section class="latest-section"><div class="section-heading"><div><p class="eyebrow">FRESH PERSPECTIVES</p><h2>{esc(section["title"])}</h2></div><a href="/blog">All stories →</a></div>{listing}</section>'
                    elif section['section_type'].startswith('category:'):
                        cat=db.execute('select * from categories where slug=?',(section['section_type'].split(':',1)[1],)).fetchone()
                        if cat:sections+=category_section(db,cat,section['title'])
            else:
                category_sections=''.join(category_section(db,c) for c in cats if db.execute("select count(*) from posts where category_id=? and status='published'",(c['id'],)).fetchone()[0])
                sections='<section class="latest-section"><div class="section-heading"><div><p class="eyebrow">FRESH PERSPECTIVES</p><h2>Latest stories</h2></div><a href="/blog">All stories →</a></div>'+listing+'</section>'+category_sections
            content='<div class="edition-line"><span>AN INDEPENDENT JOURNAL</span><span>STYLE · CULTURE · EVERYDAY LIFE</span></div>'+hero_html+ad_banner(db,'home_after_hero')+sections+ad_banner(db,'home_after_stories')+pager('/blog',int(query.get('page',['1'])[0] or 1),total,16)+'<section class="newsletter"><p class="eyebrow">THE BEYONDTOPIC LETTER</p><h2>A little inspiration, thoughtfully delivered.</h2><p>New ideas and good reads, occasionally in your inbox.</p><form action="/subscribe" method="post">'+public_csrf(public_token)+'<label class="sr-only" for="newsletter-email">Email address</label><input id="newsletter-email" name="email" type="email" placeholder="Your email address" autocomplete="email" required><label class="consent"><input type="checkbox" name="consent" value="1" required> I agree to receive BeyondTopic updates. Unsubscribe at any time.</label><button>Join the list <span>→</span></button></form><small>Preview: subscriptions are saved here; email delivery is not connected yet.</small></section>'
            return page('Explore More. Discover Beyond.',content)
        if path=='/subscribe' and method=='POST':
            f=values(); cookie=unsign(jar['bt_public_csrf'].value) if 'bt_public_csrf' in jar else None
            if not cookie or not valid_csrf(f,cookie): return page('Form expired','<h1>Please reload and subscribe again.</h1>','', '403 Forbidden')
            email=f.get('email','').strip().lower()
            if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): return page('Subscribe','<h1>Enter a valid email address.</h1>','', '400 Bad Request')
            if f.get('consent')!='1':return page('Consent required','<h1>Please agree before joining the newsletter.</h1><a href="/">Return to BeyondTopic</a>','', '400 Bad Request')
            db.execute("insert into subscribers(email,status,consent_at) values(?,'subscribed',CURRENT_TIMESTAMP) on conflict(email) do update set status='subscribed',consent_at=CURRENT_TIMESTAMP",(email,));db.commit()
            token=quote(sign('unsub:'+email))
            return page('Welcome to the letter',f'<p class="eyebrow">THE BEYONDTOPIC LETTER</p><h1>You’re on the list.</h1><p>Your address has been saved. This local preview does not send email until a newsletter provider is configured.</p><p><a class="button" href="/unsubscribe?token={token}">Unsubscribe</a></p><a href="/">Return to BeyondTopic</a>')
        if path=='/unsubscribe':
            f=values() if method=='POST' else {}
            token=query.get('token',[''])[0] if method=='GET' else f.get('token','')
            payload=unsign(token) if token else None
            email=payload[6:] if payload and payload.startswith('unsub:') else ''
            if not email:return page('Unsubscribe','<h1>This unsubscribe link is invalid.</h1><a href="/">Return home</a>','', '400 Bad Request')
            if method=='POST':
                cookie=unsign(jar['bt_public_csrf'].value) if 'bt_public_csrf' in jar else None
                if not cookie or not valid_csrf(f,cookie):return page('Form expired','<h1>Please reload and try again.</h1>','', '403 Forbidden')
                db.execute("update subscribers set status='unsubscribed' where email=?",(email,));db.commit()
                return page('Unsubscribed','<h1>You have been unsubscribed.</h1><p>We will not send BeyondTopic updates to this address.</p><a href="/">Return home</a>')
            row=db.execute("select status from subscribers where email=?",(email,)).fetchone()
            if not row or row['status']!='subscribed':return page('Unsubscribed','<h1>This address is already unsubscribed.</h1><a href="/">Return home</a>')
            return page('Manage newsletter subscription','<h1>Unsubscribe from BeyondTopic</h1><p>Confirm to stop newsletter updates for this address.</p><form method="post" action="/unsubscribe">'+public_csrf(public_token)+f'<input type="hidden" name="token" value="{esc(token)}"><button>Confirm unsubscribe</button></form>')
        if path=='/search':
            term=query.get('q',[''])[0].strip(); page_num=max(1,int(query.get('page',['1'])[0] or 1))
            search_sql="(p.title like ? or p.excerpt like ? or p.body like ? or exists(select 1 from post_tags pt join tags t on t.id=pt.tag_id where pt.post_id=p.id and t.name like ?) or exists(select 1 from categories c2 where c2.id=p.category_id and c2.name like ?) or exists(select 1 from authors a2 where a2.id=p.author_id and a2.name like ?))"
            count=db.execute("select count(*) from posts p where p.status='published' and "+search_sql,['%'+term+'%']*6).fetchone()[0] if term else 0
            rows=db.execute("select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.status='published' and "+search_sql+" order by p.published_at desc limit 12 offset ?",['%'+term+'%']*6+[(page_num-1)*12]).fetchall() if term else []
            content=f'<p class="eyebrow">THE BEYONDTOPIC ARCHIVE</p><h1>Search stories</h1><form class="search-form" role="search"><label class="sr-only" for="result-search">Search stories</label><input id="result-search" type="search" name="q" value="{esc(term)}" placeholder="What are you curious about?"><button>Search</button></form>'
            content+='<div class="grid">'+''.join(article_card(x) for x in rows)+'</div>' if rows else '<p>'+('Enter a phrase to find stories.' if not term else 'No stories matched your search.')+'</p>'
            return page('Search',content+pager('/search?q='+quote(term),page_num,count,12),noindex=True)
        if path.startswith('/blog/'):
            slug=path.rsplit('/',1)[-1]; process_due(db)
            p=db.execute("select p.*,c.name category,a.name author,a.bio,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.slug=? and p.status='published'",(slug,)).fetchone()
            if p:
                tags=db.execute('select t.* from tags t join post_tags pt on pt.tag_id=t.id where pt.post_id=?',(p['id'],)).fetchall()
                related=db.execute("select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.status='published' and p.category_id=? and p.id!=? order by p.published_at desc limit 3",(p['category_id'],p['id'])).fetchall()
                previous=db.execute("select slug,title from posts where status='published' and published_at<? order by published_at desc limit 1",(p['published_at'] or '',)).fetchone()
                following=db.execute("select slug,title from posts where status='published' and published_at>? order by published_at asc limit 1",(p['published_at'] or '',)).fetchone()
                body=render_body(p['body']); toc=table_of_contents(p['body'])
                sample_note='<p class="sample-note">This is editable starter content. Review all details and replace this sample before publishing it as verified reporting or professional advice.</p>' if p['is_sample'] else ''
                disclosure='<p class="disclosure">This article contains affiliate links. We may earn a commission if you buy through links in this article.</p>' if p['affiliate_disclosure'] else ''
                author=f'<a href="/author/{quote(p["author_slug"])}">{esc(p["author"] or "BeyondTopic Editors")}</a>' if p['author_slug'] else 'BeyondTopic Editors'
                products=db.execute('select pr.*,al.id link_id from products pr join affiliate_links al on al.product_id=pr.id where al.post_id=? and al.active=1 and pr.active=1',(p['id'],)).fetchall()
                if products and not disclosure:disclosure='<p class="disclosure">This article contains affiliate links. We may earn a commission if you buy through links in this article.</p>'
                pcards=''.join(f'<div class="card"><h3>{esc(x["name"])}</h3><p>{esc(x["description"])}</p><p>{esc(x["price"])} {esc(x["currency"])}</p><a rel="sponsored nofollow noopener" target="_blank" href="/out/{x["link_id"]}">View at {esc(x["merchant"] or "retailer")} →</a></div>' for x in products)
                tag_html=''.join(f'<a href="/tag/{quote(t["slug"])}">#{esc(t["name"])}</a> ' for t in tags)
                product_html=f'<h2>Recommended products</h2><div class="grid">{pcards}</div>' if pcards else ''
                image=f'<figure class="featured-image"><img src="{esc(p["featured_image"])}" alt="{esc(p["image_alt"])}" fetchpriority="high"><figcaption>{esc(p["image_caption"])} {("· Photo: "+esc(p["image_credit"])) if p["image_credit"] else ""}</figcaption></figure>' if p['featured_image'] else ''
                adjacent_links=(f'<a href="/blog/{quote(previous["slug"])}">← {esc(previous["title"])}</a>' if previous else '')+(f'<a href="/blog/{quote(following["slug"])}">{esc(following["title"])} →</a>' if following else '')
                adjacent=f'<nav class="pager" aria-label="Adjacent stories">{adjacent_links}</nav>' if adjacent_links else ''
                configured=db.execute("select value from settings where key='seo.canonical_base'").fetchone();base=(configured['value'] if configured and configured['value'] else os.environ.get('BEYONDTOPIC_URL','http://localhost:8000')).rstrip('/')
                story_url=base+'/blog/'+p['slug'];category_slug=quote(slugify(p['category'] or 'stories'))
                related_html=f'<section class="related"><div class="section-heading"><h2>More to explore</h2><a href="/category/{category_slug}">All {esc(p["category"] or "stories")} →</a></div><div class="grid">'+''.join(article_card(x) for x in related)+'</div></section>' if related else ''
                content=f'<nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a><span> / </span><a href="/category/{category_slug}">{esc(p["category"] or "Stories")}</a><span> / </span><span>{esc(p["title"])}</span></nav><article class="article-detail"><header class="article-head"><p class="eyebrow">{esc(p["category"] or "STORY")} {"· STARTER STORY" if p["is_sample"] else ""}</p><h1>{esc(p["title"])}</h1><p class="article-deck">{esc(p["excerpt"])}</p>{story_meta(p)}</header>{image}{ad_banner(db,"story_after_image")}{sample_note}{disclosure}{toc}<div class="prose">{body}</div><div class="tags">{tag_html}</div><p class="share">Share this story: <a href="mailto:?subject={quote(p["title"])}">Email</a> · <a rel="noopener" target="_blank" href="https://www.facebook.com/sharer/sharer.php?u={quote(story_url)}">Facebook</a></p></article>{ad_banner(db,"story_after_article")}{product_html}{related_html}{adjacent}'
                canonical=p['canonical_url'] or base+'/blog/'+p['slug']
                article_author={'@type':'Person','name':p['author']} if p['author'] else {'@type':'Organization','name':'BeyondTopic Editors'}
                schema_data={'@context':'https://schema.org','@type':'Article','headline':p['title'],'description':p['excerpt'],'datePublished':p['published_at'],'dateModified':p['updated_at'],'mainEntityOfPage':canonical,'author':article_author,'publisher':{'@type':'Organization','name':'BeyondTopic'},'image':[p['featured_image']] if p['featured_image'] else []}
                schema=json.dumps(schema_data).replace('<','\\u003c')
                content+=f'<script type="application/ld+json">{schema}</script>'
                return page(p['seo_title'] or p['title'],content,'',description=p['meta_description'] or p['excerpt'],canonical=canonical,noindex=bool(p['noindex']),social_image=p['social_image'] or p['featured_image'])
        if path.startswith('/preview/'):
            post_id=path.rsplit('/',1)[-1]; token=query.get('token',[''])[0]
            draft=db.execute('select p.*,c.name category from posts p left join categories c on c.id=p.category_id where p.id=?',(post_id,)).fetchone()
            if draft and secrets.compare_digest(token,sign(str(draft['id'])+':'+str(draft['updated_at']))):
                return page('Preview: '+draft['title'],f'<p class="eyebrow">PRIVATE PREVIEW</p><article><h1>{esc(draft["title"])}</h1><p class="dek">{esc(draft["excerpt"])}</p><div class="prose">{render_body(draft["body"])}</div></article>','', '200 OK',noindex=True)
            return page('Preview expired','<h1>Preview is unavailable or expired.</h1>','', '404 Not Found')
        if path.startswith('/preview-page/'):
            page_id=path.rsplit('/',1)[-1]; token=query.get('token',[''])[0]
            preview=db.execute('select * from pages where id=?',(page_id,)).fetchone()
            if preview and secrets.compare_digest(token,sign(str(preview['id'])+':'+str(preview['updated_at']))):
                return page('Preview: '+preview['title'],f'<p class="eyebrow">PRIVATE PREVIEW</p><article><h1>{esc(preview["title"])}</h1><div class="prose">{render_body(preview["body"])}</div></article>','',noindex=True)
            return page('Preview expired','<h1>Preview is unavailable or expired.</h1>','', '404 Not Found')
        if path.startswith('/category/'): return category_page(db,path,query,page)
        if path.startswith('/tag/'): return tag_page(db,path,query,page)
        if path.startswith('/author/'): return author_page(db,path,query,page)
        if path.startswith('/page/'): return page_view(db,path,page)
        if path.startswith('/out/'):
            item=db.execute('select affiliate_url from affiliate_links where id=? and active=1',(path.rsplit('/',1)[-1],)).fetchone()
            if item and safe_external(item['affiliate_url']):
                db.execute("insert into analytics_events(kind,path) values('affiliate_click',?)",(path,)); db.commit(); return go(item['affiliate_url'],'302 Found',[('Referrer-Policy','no-referrer')])
        if path=='/robots.txt':
            configured=db.execute("select value from settings where key='seo.canonical_base'").fetchone();base=(configured['value'] if configured and configured['value'] else os.environ.get('BEYONDTOPIC_URL','http://localhost:8000')).rstrip('/')
            return response(start_response,'User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /preview/\nDisallow: /preview-page/\nDisallow: /unsubscribe\nSitemap: '+esc(base+'/sitemap.xml')+'\n',headers=[('Content-Type','text/plain; charset=utf-8')])
        if path=='/sitemap.xml': return sitemap(db,start_response)
        redir=db.execute('select destination,code from redirects where source=? and active=1',(path,)).fetchone()
        if redir and not redirect_loops(db,path,redir['destination']): return go(redir['destination'],f'{redir["code"]} Redirect')
        return page('Not found','<section class="hero"><p class="eyebrow">404</p><h1>That page could not be found.</h1><p>Try a story archive or browse a category.</p><a href="/">Return home</a></section>'+category_nav(db),'', '404 Not Found')
    except (ValueError, KeyError, TypeError) as exc:
        return render(start_response,'Request could not be completed',f'<h1>Request could not be completed</h1><p>{esc(exc)}</p>',bool(user),'400 Bad Request',csrf=csrf)
    except Exception:
        return render(start_response,'Something went wrong','<h1>Something went wrong.</h1><p>Please try again.</p>',bool(user),'500 Internal Server Error',csrf=csrf)
    finally: db.close()

def decode_path(path):
    from urllib.parse import unquote
    return unquote(path)
def static_response(start,path,mime):
    try: data=Path(path).read_bytes()
    except OSError: return response(start,'Not found','404 Not Found')
    return response(start,data,headers=[('Content-Type',mime),('Cache-Control','public, max-age=3600')])
def media_response(start,path):
    candidate=(MEDIA_DIR/path.rsplit('/',1)[-1]).resolve()
    if candidate.parent!=MEDIA_DIR.resolve() or not candidate.is_file(): return response(start,'Not found','404 Not Found')
    return static_response(start,candidate,mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream')
def login_page(start,message='',status='200 OK',token=None):
    token=token or ''
    return render(start,'Publisher login',f'<h1>Publisher login</h1>{"<p class=error>"+esc(message)+"</p>" if message else ""}{login_form(token)}',False,status)
def login_form(token): return f'<form method="post"><input type="hidden" name="csrf" value="{esc(token)}">{field("username","Username","text","",True)}{field("password","Password","password","",True)}<button>Sign in</button></form>'
def public_csrf(value): return f'<input type="hidden" name="csrf" value="{esc(value or "")}">'
def table(headers,rows): return '<div class="table-wrap"><table><thead><tr>'+''.join(f'<th>{esc(x)}</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{c}</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def form_start(csrf,action='',multipart=False):
    enc=' enctype="multipart/form-data"' if multipart else ''
    return f'<form method="post" action="{esc(action)}"{enc}><input type="hidden" name="csrf" value="{esc(csrf)}">'
def options(rows,blank=True): return ([('','— none —')] if blank else [])+[(x['id'],x['name']) for x in rows]
def bool_value(f,key): return 1 if (f.get(key) if isinstance(f,dict) else f.getfirst(key)) else 0
def table_of_contents(body):
    headings=[x.lstrip('# ').strip() for x in body.splitlines() if x.startswith('# ')]
    return '<nav class="toc"><b>In this story</b><ol>'+''.join(f'<li><a href="#{quote(slugify(x))}">{esc(x)}</a></li>' for x in headings)+'</ol></nav>' if headings else ''
def render_body(body):
    out=[]
    for line in body.splitlines():
        s=line.strip()
        if not s: continue
        if s.startswith('# '): title=s[2:].strip(); out.append(f'<h2 id="{esc(slugify(title))}">{esc(title)}</h2>')
        elif s.startswith('## '): title=s[3:].strip(); out.append(f'<h3 id="{esc(slugify(title))}">{esc(title)}</h3>')
        elif s.startswith('> '): out.append(f'<blockquote>{esc(s[2:])}</blockquote>')
        elif s.startswith('- '): out.append(f'<p class="list-item">• {esc(s[2:])}</p>')
        else: out.append(f'<p>{esc(s)}</p>')
    return ''.join(out)
def story_hero(p,active=True):
    meta=story_meta(p)
    sample='<span class="sample-badge">Starter story</span>' if 'is_sample' in p.keys() and p['is_sample'] else ''
    image_class='hero-image' if active else 'hero-image hero-image--deferred'
    return f'<section class="hero">{story_image(p,image_class)}<div class="hero-copy"><p class="eyebrow">THE EDITOR’S PICK <span>·</span> {esc(p["category"] or "EDITORIAL")} {sample}</p><h1><a href="/blog/{quote(p["slug"])}">{esc(p["title"])}</a></h1><p class="hero-deck">{esc(p["excerpt"])}</p>{meta}<a class="button" href="/blog/{quote(p["slug"])}">Read the story <span>↗</span></a></div></section>'
def story_hero_carousel(stories):
    if len(stories)<2:return story_hero(stories[0])
    slides=[]
    for i,story in enumerate(stories):
        html=story_hero(story,active=(i==0)).replace('<section class="hero">',f'<section class="hero hero-slide{" is-active" if i==0 else ""}" data-hero-slide aria-hidden="{"false" if i==0 else "true"}"{"" if i==0 else " inert"}>',1)
        slides.append(html)
    controls=''.join('<button type="button" data-hero-go="{}" aria-label="Show featured story {}: {}"{}></button>'.format(i,i+1,esc(story['title']),' aria-current="true"' if i==0 else '') for i,story in enumerate(stories))
    return f'<div class="hero-carousel" data-hero-carousel aria-label="Featured stories"><div class="hero-slides">{"".join(slides)}</div><div class="hero-controls"><div class="hero-pagination" role="group" aria-label="Choose a featured story">{controls}</div><span class="hero-count" aria-live="polite">01 / {len(stories):02d}</span><div class="hero-arrows"><button type="button" data-hero-pause aria-label="Pause featured story rotation">Pause</button><button type="button" data-hero-prev aria-label="Previous featured story">←</button><button type="button" data-hero-next aria-label="Next featured story">→</button></div></div></div>'
def story_image(p,extra=''):
    src=p['featured_image'] if 'featured_image' in p.keys() else ''
    if not src:return ''
    loading='eager' if extra=='hero-image' else 'lazy'; priority=' fetchpriority="high"' if extra=='hero-image' else ''
    return f'<div class="{extra}"><img src="{esc(src)}" alt="{esc(p["image_alt"] if "image_alt" in p.keys() else "Editorial photograph")}" loading="{loading}"{priority}><span class="image-credit">{esc(p["image_credit"] if "image_credit" in p.keys() else "Unsplash")}</span></div>'
def story_meta(p):
    keys=p.keys(); author=p['author'] if 'author' in keys and p['author'] else 'BeyondTopic Editors'
    author_slug=p['author_slug'] if 'author_slug' in keys else ''
    photo=p['author_photo'] if 'author_photo' in keys else ''
    avatar=f'<img class="byline-avatar" src="{esc(photo)}" alt="" loading="lazy">' if safe_profile_image(photo) else ''
    author_html=f'<a class="story-author" href="/author/{quote(author_slug)}">{avatar}{esc(author)}</a>' if author_slug else f'<span class="story-author">{avatar}{esc(author)}</span>'
    published=p['published_at'] if 'published_at' in keys and p['published_at'] else ''
    day=published[:10]
    minutes=max(1,len((p['body'] or '').split())//200)
    date_html=f'<time datetime="{esc(day)}">{esc(day)}</time>' if day else ''
    return f'<div class="story-meta"><span>{author_html}</span>{date_html}<span>{minutes} min read</span></div>'
def article_card(p):
    category=p['category'] if 'category' in p.keys() else ''
    sample='<span class="sample-badge">Starter</span>' if 'is_sample' in p.keys() and p['is_sample'] else ''
    return f'<article class="card">{story_image(p,"card-image")}<div class="card-copy"><p class="eyebrow">{esc(category or "EDITORIAL")} {sample}</p><h3><a href="/blog/{quote(p["slug"])}">{esc(p["title"])}</a></h3><p>{esc(p["excerpt"])}</p>{story_meta(p)}<a class="read-link" href="/blog/{quote(p["slug"])}">Continue reading <span>↗</span></a></div></article>'
def pager(base,current,total,limit):
    pages=(total+limit-1)//limit
    if pages<2:return ''
    links=[]
    if current>1: links.append(f'<a href="{base}{"&" if "?" in base else "?"}page={current-1}">← Newer</a>')
    links.append(f'<span>Page {current} of {pages}</span>')
    if current<pages: links.append(f'<a href="{base}{"&" if "?" in base else "?"}page={current+1}">Older →</a>')
    return '<nav class="pager">'+' · '.join(links)+'</nav>'
def category_nav(db): return '<nav>'+''.join(f'<a href="/category/{quote(x["slug"])}">{esc(x["name"])}</a> ' for x in db.execute('select * from categories where parent_id is null and active=1 order by name'))+'</nav>'
def category_section(db,c,heading=None):
    if not c:return ''
    rows=db.execute('select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.category_id=? and p.status="published" order by p.published_at desc limit 5',(c['id'],)).fetchall()
    if not rows:return ''
    title=heading or c['name']
    carousel_id='carousel-'+esc(c['slug'])
    controls=f'<div class="carousel-controls"><span class="carousel-count" aria-live="polite">01 / {len(rows):02d}</span><span class="carousel-note">Five stories · moves automatically</span><div class="carousel-buttons"><button type="button" data-pause aria-label="Pause automatic story scrolling">Pause</button><button type="button" data-prev aria-label="Previous {esc(c["name"])} stories" aria-controls="{carousel_id}">←</button><button type="button" data-next aria-label="Next {esc(c["name"])} stories" aria-controls="{carousel_id}">→</button></div></div>'
    return f'<section class="category-section"><div class="section-heading"><div><p class="eyebrow">THE JOURNAL · {esc(c["name"])}</p><h2>{esc(title)}</h2></div><a href="/category/{quote(c["slug"])}">Explore all {esc(c["name"])} stories <span>→</span></a></div><div class="carousel" data-carousel aria-label="{esc(c["name"])} stories"><div id="{carousel_id}" class="grid carousel-track" tabindex="0">'+''.join(article_card(x) for x in rows)+'</div>'+controls+'</div></section>'
def category_page(db,path,query,page):
    slug=path.rsplit('/',1)[-1]; cat=db.execute('select * from categories where slug=? and active=1',(slug,)).fetchone()
    if not cat:return page('Not found','<h1>Category not found</h1>','', '404 Not Found')
    children=db.execute('select id from categories where parent_id=?',(cat['id'],)).fetchall(); ids=[cat['id']]+[x['id'] for x in children]; marks=','.join('?' for _ in ids)
    total=db.execute(f"select count(*) from posts where category_id in ({marks}) and status='published'",ids).fetchone()[0]; num=max(1,int(query.get('page',['1'])[0] or 1))
    rows=db.execute(f"select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where p.category_id in ({marks}) and p.status='published' order by p.published_at desc limit 12 offset ?",ids+[(num-1)*12]).fetchall()
    subcats=''.join(f'<a href="/category/{quote(x["slug"])}">{esc(x["name"])}</a>' for x in db.execute('select * from categories where parent_id=? and active=1',(cat['id'],)))
    intro=f'<p class="eyebrow">THE JOURNAL</p><h1>{esc(cat["name"])}</h1><p class="category-deck">{esc(cat["description"])}</p>'+ (f'<nav class="subcats" aria-label="Subcategories">{subcats}</nav>' if subcats else '')
    return page(cat['name'],intro+'<div class="grid">'+''.join(article_card(x) for x in rows)+'</div>'+pager('/category/'+quote(slug),num,total,12),'',description=cat['description'] or cat['name'])
def tag_page(db,path,query,page):
    slug=path.rsplit('/',1)[-1]; tag=db.execute('select * from tags where slug=?',(slug,)).fetchone()
    if not tag:return page('Not found','<h1>Tag not found</h1>','', '404 Not Found')
    total=db.execute("select count(*) from post_tags pt join posts p on p.id=pt.post_id where pt.tag_id=? and p.status='published'",(tag['id'],)).fetchone()[0]; num=max(1,int(query.get('page',['1'])[0] or 1))
    rows=db.execute("select p.*,c.name category,a.name author,a.slug author_slug,a.photo_url author_photo from post_tags pt join posts p on p.id=pt.post_id left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id where pt.tag_id=? and p.status='published' order by p.published_at desc limit 12 offset ?",(tag['id'],(num-1)*12)).fetchall()
    return page(tag['name'],f'<p class="eyebrow">TOPIC</p><h1>Stories tagged {esc(tag["name"])}</h1><div class="grid">'+''.join(article_card(x) for x in rows)+'</div>'+pager('/tag/'+quote(slug),num,total,12))
def author_page(db,path,query,page):
    slug=path.rsplit('/',1)[-1]; a=db.execute('select * from authors where slug=?',(slug,)).fetchone()
    if not a:return page('Not found','<h1>Author not found</h1>','', '404 Not Found')
    rows=db.execute("select p.*,c.name category from posts p left join categories c on c.id=p.category_id where p.author_id=? and p.status='published' order by p.published_at desc",(a['id'],)).fetchall()
    photo=f'<img class="author-photo" src="{esc(a["photo_url"])}" alt="Portrait of {esc(a["name"])}">' if safe_profile_image(a['photo_url']) else ''
    socials=[]
    for line in (a['social_links'] or '').splitlines():
        url=line.strip()
        if safe_external(url):socials.append(f'<a rel="me noopener" href="{esc(url)}">{esc(url)}</a>')
    email=f'<a href="mailto:{quote(a["email"])}">Email {esc(a["name"])}</a>' if a['email'] else ''
    return page(a['name'],f'<p class="eyebrow">{esc(a["job_title"])}</p>{photo}<h1>{esc(a["name"])}</h1><p class="dek">{esc(a["bio"])}</p><p class="socials">'+ ' · '.join(socials+[email])+f'</p><h2>Stories</h2><div class="grid">'+''.join(article_card(x) for x in rows)+'</div>')
def page_view(db,path,page):
    slug=path.rsplit('/',1)[-1]; p=db.execute("select * from pages where slug=? and status='published'",(slug,)).fetchone()
    if not p:return page('Not found','<h1>Page not found</h1>','', '404 Not Found')
    configured=db.execute("select value from settings where key='seo.canonical_base'").fetchone();base=(configured['value'] if configured and configured['value'] else os.environ.get('BEYONDTOPIC_URL','http://localhost:8000')).rstrip('/')
    return page(p['seo_title'] or p['title'],f'<article><h1>{esc(p["title"])}</h1><div class="prose">{render_body(p["body"])}</div></article>','',description=p['meta_description'] or p['title'],canonical=p['canonical_url'] or base+'/page/'+p['slug'],noindex=bool(p['noindex']),social_image=p['social_image'])
def sitemap(db,start):
    setting=db.execute("select value from settings where key='seo.canonical_base'").fetchone()
    base=(setting['value'] if setting and setting['value'] else os.environ.get('BEYONDTOPIC_URL','http://localhost:8000')).rstrip('/')
    paths=['/']+['/blog/'+x['slug'] for x in db.execute("select slug from posts where status='published' and noindex=0")]+['/page/'+x['slug'] for x in db.execute("select slug from pages where status='published' and noindex=0")]+['/category/'+x['slug'] for x in db.execute('select slug from categories where active=1')]+['/tag/'+x['slug'] for x in db.execute('select t.slug from tags t where exists(select 1 from post_tags pt join posts p on p.id=pt.post_id where pt.tag_id=t.id and p.status="published")')]+['/author/'+x['slug'] for x in db.execute('select a.slug from authors a where exists(select 1 from posts p where p.author_id=a.id and p.status="published")')]
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{esc(base+u)}</loc></url>' for u in paths)+'</urlset>'
    return response(start,xml,headers=[('Content-Type','application/xml; charset=utf-8')])
def safe_external(url):
    from urllib.parse import urlparse
    return urlparse(url or '').scheme in ('http','https') and bool(urlparse(url).netloc)
def safe_profile_image(url):
    if safe_external(url):return True
    return bool(re.fullmatch(r'/media/[A-Za-z0-9_.-]+',url or ''))
def redirect_loops(db,source,dest):
    seen={source}; current=dest
    for _ in range(20):
        if current in seen:return True
        seen.add(current); row=db.execute('select destination from redirects where source=? and active=1',(current,)).fetchone()
        if not row:return False
        current=row['destination']
    return True
def process_due(db):
    db.execute("update posts set status='published',published_at=coalesce(published_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP where status='scheduled' and scheduled_at is not null and scheduled_at<=datetime('now')")
    db.execute("update pages set status='published',updated_at=CURRENT_TIMESTAMP where status='scheduled' and scheduled_at is not null and scheduled_at<=datetime('now')"); db.commit()
def scheduler():
    while True:
        try:
            with database.connect() as db: process_due(db)
        except Exception: pass
        time.sleep(20)

def posts_list(db,page,query,user,method='GET',form_data=None,csrf='',go=None,audit=None):
    form_data=form_data or {}
    if method=='POST' and form_data.get('action')=='bulk':
        if user['role'] not in ('admin','editor'):
            return page('Bulk action unavailable','<h1>Only editors and administrators can change multiple stories at once.</h1>',True,'403 Forbidden')
        ids=[]
        for value in form_data.get('ids','').split(',')[:100]:
            if value.isdigit():ids.append(int(value))
        ids=sorted(set(ids));action=form_data.get('bulk_action','')
        states={'draft':'draft','publish':'published','archive':'archived','trash':'trashed'}
        if not ids or action not in states:return page('Choose stories and an action','<h1>Select at least one story and choose a valid action.</h1>',True,'400 Bad Request')
        state=states[action];marks=','.join('?' for _ in ids)
        db.execute(f'update posts set status=?,published_at=case when ?="published" then coalesce(published_at,CURRENT_TIMESTAMP) else published_at end,trashed_at=case when ?="trashed" then CURRENT_TIMESTAMP else null end,updated_at=CURRENT_TIMESTAMP where id in ({marks})',(state,state,state,*ids));db.commit()
        if audit:audit('bulk update stories',f'{len(ids)} stories set to {state}')
        if go:return go('/admin/posts')
    where=[]; args=[]
    for key,col in [('status','p.status'),('category','p.category_id'),('author','p.author_id')]:
        val=query.get(key,[''])[0]
        if val: where.append(col+'=?'); args.append(val)
    sample_filter=query.get('sample',[''])[0]
    if sample_filter in ('0','1'):where.append('p.is_sample=?');args.append(int(sample_filter))
    term=query.get('q',[''])[0].strip()
    if term: where.append('(p.title like ? or p.excerpt like ?)'); args += ['%'+term+'%']*2
    tag_term=query.get('tag',[''])[0].strip()
    if tag_term:where.append('exists(select 1 from post_tags pt join tags t on t.id=pt.tag_id where pt.post_id=p.id and t.id=?)');args.append(tag_term)
    after=query.get('from',[''])[0];before=query.get('to',[''])[0]
    if after:where.append('date(p.published_at)>=date(?)');args.append(after)
    if before:where.append('date(p.published_at)<=date(?)');args.append(before)
    if user['role'] in ('author','contributor'):where.append('p.author_id=?');args.append(user['author_id'] or -1)
    clause=(' where '+' and '.join(where)) if where else ''; total=db.execute('select count(*) from posts p'+clause,args).fetchone()[0]; num=max(1,int(query.get('page',['1'])[0] or 1))
    rows=db.execute('select p.*,c.name category,a.name author,a.photo_url author_photo from posts p left join categories c on c.id=p.category_id left join authors a on a.id=p.author_id'+clause+' order by p.updated_at desc limit 30 offset ?',args+[(num-1)*30]).fetchall()
    status_options=[('', 'All statuses')]+[(s,s.replace('_',' ').title()) for s in STATUS]
    sample_options=[('', 'All content'),('1','Starter stories'),('0','Original stories')]
    tag_options=options(db.execute('select id,name from tags order by name').fetchall())
    filters='<form class="filters" method="get">'+field('q','Search','search',term)+field('status','Status','select',query.get('status',[''])[0],False,status_options)+field('category','Category','select',query.get('category',[''])[0],False,options(db.execute('select id,name from categories order by name').fetchall()))+field('author','Author','select',query.get('author',[''])[0],False,options(db.execute('select id,name from authors order by name').fetchall()))+field('tag','Tag','select',tag_term,False,tag_options)+field('sample','Content type','select',sample_filter,False,sample_options)+field('from','Published from','date',after)+field('to','Published to','date',before)+'<button>Apply filters</button></form>'
    rows_html=[]
    for x in rows:
        thumb=f'<img class="table-thumb" src="{esc(x["featured_image"])}" alt="">' if x['featured_image'] else '<span class="no-thumb">—</span>'
        seo='Ready' if x['seo_title'] and x['meta_description'] else 'Needs review'
        action=f'<a href="/admin/posts/{x["id"]}">Edit</a>' + (f' · <a href="/blog/{quote(x["slug"])}">View</a>' if x['status']=='published' else '')
        checkbox=f'<input class="story-select" type="checkbox" value="{x["id"]}" aria-label="Select {esc(x["title"])}">' if user['role'] in ('admin','editor') else ''
        rows_html.append([checkbox+thumb+f'<a href="/admin/posts/{x["id"]}">{esc(x["title"])}</a>{" <span class=sample-badge>Starter</span>" if x["is_sample"] else ""}',esc(x['author']),esc(x['category']),esc(x['status']),esc(x['published_at'] or x['scheduled_at'] or '—'),esc(x['updated_at']),seo,action])
    params={key:query[key][0] for key in ('q','status','category','author','tag','sample','from','to') if query.get(key,[''])[0]}
    base='/admin/posts'+(('?'+urlencode(params)) if params else '')
    headers=(['Story','Author','Category','Status','Publication','Modified','SEO','Actions'] if user['role'] not in ('admin','editor') else ['Select','Author','Category','Status','Publication','Modified','SEO','Actions'])
    listing=table(headers,rows_html) if rows_html else '<p class="empty-state">No stories match these filters. Try a broader search or create a new story.</p>'
    bulk=form_start(csrf,action='/admin/posts')+'<label class="select-all"><input type="checkbox" data-select-all aria-label="Select all stories on this page"> Select all</label><input type="hidden" name="action" value="bulk"><input type="hidden" name="ids" id="bulk-ids"><label class="sr-only" for="bulk-action">Bulk story action</label><select name="bulk_action" id="bulk-action"><option value="">With selected…</option><option value="publish">Publish</option><option value="draft">Move to draft</option><option value="archive">Archive</option><option value="trash">Move to trash</option></select><button>Apply</button></form>' if user['role'] in ('admin','editor') else ''
    return page('Stories',f'<p class="eyebrow">EDITORIAL WORKSPACE</p><h1>Stories</h1><a class="button" href="/admin/posts/new">New story</a>{filters}<div class="bulk-bar">{bulk}<span>Select up to 100 stories from this page.</span></div>{listing}'+pager(base,num,total,30),True)

def post_form(db,values,csrf,post_id=None,user=None):
    cats=options(db.execute('select id,name from categories where active=1 order by name').fetchall()); authors=options(db.execute('select id,name from authors where id=?',(user['author_id'],)).fetchall(),False) if user and user['role'] in ('author','contributor') and user['author_id'] else options(db.execute('select id,name from authors order by name').fetchall(),False)
    tags=db.execute('select t.name from tags t join post_tags pt on pt.tag_id=t.id where pt.post_id=?',(post_id,)).fetchall() if post_id else []
    htmlform=form_start(csrf)
    htmlform+=field('title','Title','text',values.get('title',''),True)+field('slug','URL slug','text',values.get('slug',''))+field('excerpt','Subtitle / excerpt','textarea',values.get('excerpt',''))
    body_field=field('body','Story content','textarea',values.get('body','')).replace('<textarea name="body"','<textarea id="story-body" name="body"')
    htmlform+='<div class="editor-tools" aria-label="Story formatting"><span>INSERT</span><button type="button" data-insert="# ">Heading</button><button type="button" data-insert="## ">Subheading</button><button type="button" data-insert="&gt; ">Quote</button><button type="button" data-insert="- ">List item</button><button type="button" id="preview-toggle" aria-expanded="false">Preview</button></div>'+body_field+'<div id="story-preview" class="prose editor-preview" hidden></div>'
    media=db.execute('select id,filename,alt from media order by id desc').fetchall()
    images=[('', '— no featured image —')]+[(f'/media/{x["filename"]}',x['alt'] or x['filename']) for x in media]
    htmlform+=field('category_id','Primary category','select',values.get('category_id',''),False,cats)+field('author_id','Author','select',values.get('author_id',''),False,authors)+field('tags','Tags (comma separated)','text',', '.join(x['name'] for x in tags))
    htmlform+=field('featured_image','Featured image','select',values.get('featured_image',''),False,images)+field('image_alt','Featured image alt text','text',values.get('image_alt',''))+field('image_caption','Image caption','text',values.get('image_caption',''))+field('image_credit','Image credit','text',values.get('image_credit',''))
    htmlform+=field('status','Workflow status','select',values.get('status','draft'),False,[(x,x.replace('_',' ').title()) for x in STATUS])+field('scheduled_at','Schedule ('+os.environ.get('BEYONDTOPIC_TIMEZONE','Asia/Kolkata')+')','datetime-local',display_schedule(values.get('scheduled_at')))+field('featured','Featured on homepage','checkbox',values.get('featured',0))+field('is_sample','Label as editable starter content','checkbox',values.get('is_sample',0))+field('affiliate_disclosure','Show affiliate disclosure','checkbox',values.get('affiliate_disclosure',0))
    htmlform+=field('seo_title','SEO title','text',values.get('seo_title',''))+field('meta_description','Meta description','textarea',values.get('meta_description',''))+field('canonical_url','Canonical URL','url',values.get('canonical_url',''))+field('social_image','Social sharing image URL','url',values.get('social_image',''))+field('noindex','Ask search engines not to index','checkbox',values.get('noindex',0))
    htmlform+='<button>Save story</button></form>'
    if post_id: htmlform+=f'<form method="post" action="/admin/posts/{post_id}/restore"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="secondary">Restore latest revision</button></form><form method="post" action="/admin/posts/{post_id}/delete" onsubmit="return confirm(\'Move this story to trash? It can be restored later.\')"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="danger">Move to trash</button></form>'
    return htmlform
def edit_post(db,path,method,f,user,csrf,page,go,audit):
    if path.endswith('/delete'):
        post_id=int(path.split('/')[-2]);db.execute("update posts set status='trashed',trashed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP where id=?",(post_id,));db.commit();audit('trash story',str(post_id));return go('/admin/posts')
    is_new=path.endswith('/new');post_id=None if is_new else int(path.split('/')[-2] if path.endswith('/restore') else path.rsplit('/',1)[-1]);post=db.execute('select * from posts where id=?',(post_id,)).fetchone() if post_id else None
    if not is_new and not post:return page('Not found','<h1>Story not found</h1>',True,'404 Not Found')
    if user['role'] in ('author','contributor') and post and post['author_id']!=user['author_id']:return page('Not found','<h1>Story not found</h1>',True,'404 Not Found')
    if path.endswith('/restore'):
        pid=int(path.split('/')[-2]); rev=db.execute('select * from post_revisions where post_id=? order by id desc limit 1',(pid,)).fetchone()
        if rev:
            data=json.loads(rev['snapshot']);db.execute('begin immediate')
            category_id=data['category_id'] if data['category_id'] is None or db.execute('select id from categories where id=?',(data['category_id'],)).fetchone() else post['category_id']
            db.execute('update posts set title=?,slug=?,excerpt=?,body=?,status=?,author_id=?,category_id=?,featured=?,affiliate_disclosure=?,seo_title=?,meta_description=?,scheduled_at=?,canonical_url=?,social_image=?,noindex=?,is_sample=?,featured_image=?,image_alt=?,image_caption=?,image_credit=?,updated_at=CURRENT_TIMESTAMP,trashed_at=case when ?="trashed" then CURRENT_TIMESTAMP else null end where id=?',(data['title'],data['slug'],data['excerpt'],data['body'],data['status'],data['author_id'],category_id,data['featured'],data['affiliate_disclosure'],data['seo_title'],data['meta_description'],data['scheduled_at'],data['canonical_url'],data['social_image'],data['noindex'],data.get('is_sample',0),data['featured_image'],data['image_alt'],data['image_caption'],data['image_credit'],data['status'],pid))
            db.execute('delete from post_tags where post_id=?',(pid,))
            for name in data['tags']:
                tag_slug=slugify(name);db.execute('insert or ignore into tags(name,slug) values(?,?)',(name,tag_slug));tag_id=db.execute('select id from tags where slug=?',(tag_slug,)).fetchone()[0];db.execute('insert or ignore into post_tags(post_id,tag_id) values(?,?)',(pid,tag_id))
            db.commit(); audit('restore revision',str(pid))
        return go(f'/admin/posts/{pid}')
    if method=='POST':
        title=f.get('title','').strip(); slug=slugify(f.get('slug') or title)
        if not title:return page('Title required','<h1>Title is required.</h1>'+post_form(db,f,csrf,post_id,user),True,'400 Bad Request')
        status=f.get('status','draft') if f.get('status') in STATUS else 'draft'; category=int(f['category_id']) if f.get('category_id','').isdigit() else None; author=(user['author_id'] if user['role']=='author' else int(f['author_id']) if f.get('author_id','').isdigit() else None)
        if user['role'] in ('author','contributor') and status not in ('draft','pending_review'):return page('Approval required','<h1>Authors can save drafts or submit for review.</h1>',True,'403 Forbidden')
        try:schedule=normalize_schedule(f.get('scheduled_at',''))
        except (ValueError,KeyError) as exc:return page('Invalid schedule',f'<h1>{esc(exc)}</h1>'+post_form(db,f,csrf,post_id,user),True,'400 Bad Request')
        if status=='scheduled' and not schedule: return page('Schedule required','<h1>Add a publication time for a scheduled story.</h1>'+post_form(db,f,csrf,post_id,user),True,'400 Bad Request')
        if status=='published' and post and post['slug']!=slug: add_slug_redirect(db,'/blog/'+post['slug'],'/blog/'+slug)
        params=(title,slug,f.get('excerpt',''),f.get('body',''),status,author,category,bool_value(f,'featured'),bool_value(f,'affiliate_disclosure'),f.get('seo_title',''),f.get('meta_description',''),schedule,f.get('canonical_url',''),f.get('social_image',''),bool_value(f,'noindex'),bool_value(f,'is_sample'))
        try:
            db.execute('begin immediate')
            if post:
                snapshot={k:post[k] for k in ('title','slug','excerpt','body','status','author_id','category_id','featured','affiliate_disclosure','seo_title','meta_description','scheduled_at','canonical_url','social_image','noindex','is_sample','featured_image','image_alt','image_caption','image_credit')}
                snapshot['tags']=[x['name'] for x in db.execute('select t.name from tags t join post_tags pt on pt.tag_id=t.id where pt.post_id=?',(post_id,))]
                db.execute('insert into post_revisions(post_id,snapshot,editor) values(?,?,?)',(post_id,json.dumps(snapshot),user['username']))
                db.execute('update posts set title=?,slug=?,excerpt=?,body=?,status=?,author_id=?,category_id=?,featured=?,affiliate_disclosure=?,seo_title=?,meta_description=?,scheduled_at=?,canonical_url=?,social_image=?,noindex=?,is_sample=?,featured_image=?,image_alt=?,image_caption=?,image_credit=?,updated_at=CURRENT_TIMESTAMP,published_at=case when ?="published" then coalesce(published_at,CURRENT_TIMESTAMP) else published_at end,trashed_at=case when ?="trashed" then CURRENT_TIMESTAMP else null end where id=?',params+(f.get('featured_image',''),f.get('image_alt',''),f.get('image_caption',''),f.get('image_credit',''),status,status,post_id))
            else:
                inserted=db.execute('insert into posts(title,slug,excerpt,body,status,author_id,category_id,featured,affiliate_disclosure,seo_title,meta_description,scheduled_at,canonical_url,social_image,noindex,is_sample,featured_image,image_alt,image_caption,image_credit,published_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,case when ?="published" then CURRENT_TIMESTAMP else null end)',params+(f.get('featured_image',''),f.get('image_alt',''),f.get('image_caption',''),f.get('image_credit',''),status))
                post_id=inserted.lastrowid
            db.execute('delete from post_tags where post_id=?',(post_id,))
            for tag_name in [x.strip() for x in f.get('tags','').split(',') if x.strip()]:
                tag_slug=slugify(tag_name); db.execute('insert or ignore into tags(name,slug) values(?,?)',(tag_name,tag_slug)); tag_id=db.execute('select id from tags where slug=?',(tag_slug,)).fetchone()[0]; db.execute('insert into post_tags(post_id,tag_id) values(?,?)',(post_id,tag_id))
            db.commit(); audit('save story',title)
        except Exception as exc:
            db.rollback(); return page('Unable to save',f'<h1>Unable to save</h1><p>{esc(exc)}</p>'+post_form(db,f,csrf,post_id,user),True,'400 Bad Request')
        return go('/admin/posts')
    vals=dict(post) if post else {}
    preview=f'<p><a class="button secondary" href="/preview/{post_id}?token={quote(sign(str(post_id)+":"+str(post["updated_at"])))}">Preview saved story ↗</a></p>' if post else ''
    return page('Edit story' if post else 'New story',f'<p class="eyebrow"><a href="/admin/posts">Stories</a> / Studio editor</p><h1>{"Edit story" if post else "Create a story"}</h1>{preview}'+post_form(db,vals,csrf,post_id,user),True)
def add_slug_redirect(db,source,destination):
    if source!=destination and not redirect_loops(db,source,destination): db.execute('insert or ignore into redirects(source,destination,code,active,notes) values(?,?,301,1,?)',(source,destination,'Automatic URL change'))

def category_form(db,csrf,values=None,cid=None):
    values=values or {}; parents=options(db.execute('select id,name from categories where id!=? order by name',(cid or -1,)).fetchall())
    return form_start(csrf)+field('name','Name','text',values.get('name',''),True)+field('slug','Slug','text',values.get('slug',''))+field('description','Description','textarea',values.get('description',''))+field('parent_id','Parent category','select',values.get('parent_id',''),False,parents)+field('active','Enabled','checkbox',values.get('active',1))+'<button>Save category</button></form>'
def manage_categories(db,path,method,f,csrf,page,go,audit):
    edit=re.fullmatch(r'/admin/categories/(\d+)',path); cid=int(edit.group(1)) if edit else None
    if method=='POST':
        if f.get('action')=='delete':
            target=int(f.get('category_id','0')); replacement=int(f.get('replacement_id','0')) or None
            if not db.execute('select id from categories where id=?',(target,)).fetchone():return page('Category missing','<h1>The category no longer exists.</h1>',True,'404 Not Found')
            if target==replacement:return page('Invalid reassignment','<h1>A category cannot replace itself.</h1>',True,'400 Bad Request')
            uses=db.execute('select count(*) from posts where category_id=?',(target,)).fetchone()[0]; children=db.execute('select count(*) from categories where parent_id=?',(target,)).fetchone()[0]
            if (uses or children) and not replacement:return page('Reassignment required','<h1>Choose a replacement category before deleting a category that has articles or child categories.</h1>',True,'400 Bad Request')
            if replacement and not db.execute('select id from categories where id=?',(replacement,)).fetchone():return page('Replacement missing','<h1>Choose an existing replacement category.</h1>',True,'400 Bad Request')
            cursor=replacement; ancestors=set()
            while cursor and cursor not in ancestors:
                if cursor==target:return page('Invalid reassignment','<h1>Choose a category outside the category being removed.</h1>',True,'400 Bad Request')
                ancestors.add(cursor); row=db.execute('select parent_id from categories where id=?',(cursor,)).fetchone();cursor=row['parent_id'] if row else None
            db.execute('begin immediate')
            if replacement:
                db.execute('update posts set category_id=? where category_id=?',(replacement,target));db.execute('update categories set parent_id=? where parent_id=?',(replacement,target))
            db.execute('delete from categories where id=?',(target,));db.commit();audit('delete category',str(target));return go('/admin/categories')
        name=f.get('name','').strip(); slug=slugify(f.get('slug') or name); par=int(f['parent_id']) if f.get('parent_id','').isdigit() else None
        try:
            cursor=par; visited=set()
            while cursor and cursor not in visited:
                if cursor==cid:raise ValueError('A category cannot be nested inside itself.')
                visited.add(cursor); row=db.execute('select parent_id from categories where id=?',(cursor,)).fetchone();cursor=row['parent_id'] if row else None
            if cid:
                previous=db.execute('select slug,active from categories where id=?',(cid,)).fetchone()
                if previous and previous['active'] and previous['slug']!=slug:add_slug_redirect(db,'/category/'+previous['slug'],'/category/'+slug)
                db.execute('update categories set name=?,slug=?,description=?,parent_id=?,active=? where id=?',(name,slug,f.get('description',''),par,bool_value(f,'active'),cid))
            else: db.execute('insert into categories(name,slug,description,parent_id,active) values(?,?,?,?,?)',(name,slug,f.get('description',''),par,bool_value(f,'active')))
            db.commit(); audit('save category',name); return go('/admin/categories')
        except Exception as e:return page('Category conflict',f'<h1>Cannot save category</h1><p>{esc(e)}</p>'+category_form(db,csrf,f,cid),True,'400 Bad Request')
    if cid:
        cat=db.execute('select * from categories where id=?',(cid,)).fetchone()
        if not cat:return page('Not found','<h1>Category not found</h1>',True,'404 Not Found')
        if method=='GET':return page('Edit category',f'<h1>Edit category</h1>'+category_form(db,csrf,dict(cat),cid),True)
    rows=db.execute('select c.*,p.name parent,(select count(*) from posts where category_id=c.id) used from categories c left join categories p on p.id=c.parent_id order by coalesce(p.name,c.name),c.parent_id,c.name').fetchall()
    choices=options(db.execute('select id,name from categories order by name').fetchall())
    actions=[]
    for x in rows:
        action_form=form_start(csrf)+f'<a href="/admin/categories/{x["id"]}">Edit</a> · '+field('category_id','', 'hidden',x['id'])+field('replacement_id','Reassign to','select','',False,[('', '— choose —')]+[(a['id'],a['name']) for a in db.execute('select id,name from categories where id!=? order by name',(x['id'],))])+f'<button name="action" value="delete" onclick="return confirm(\'Delete this category after reassigning any stories and subcategories?\')">Delete safely</button></form>'
        actions.append([esc(x['name']),'/'+esc(x['slug']),esc(x['parent'] or '—'),str(x['used']),('Enabled' if x['active'] else 'Disabled'),action_form])
    body='<h1>Categories</h1>'+category_form(db,csrf)+'<h2>Category structure</h2>'+table(['Category','URL','Parent','Stories','Status','Actions'],actions)
    return page('Categories',body,True)

def manage_pages(db,method,f,query,user,csrf,page,go,audit):
    edit_id=int(query.get('edit',['0'])[0] or 0); old=db.execute('select * from pages where id=?',(edit_id,)).fetchone() if edit_id else None
    if method=='POST':
        if f.get('action')=='duplicate':
            source=db.execute('select * from pages where id=?',(f.get('id'),)).fetchone()
            if source:
                base=slugify(source['slug']+'-copy');slug=base;n=2
                while db.execute('select 1 from pages where slug=?',(slug,)).fetchone():slug=f'{base}-{n}';n+=1
                db.execute('insert into pages(title,slug,body,status,seo_title,meta_description,template,canonical_url) values(?,?,?,?,?,?,?,?)',(source['title']+' (copy)',slug,source['body'],'draft',source['seo_title'],source['meta_description'],source['template'],''));db.commit();audit('duplicate page',source['title'])
            return go('/admin/pages')
        if f.get('action')=='trash':
            db.execute("update pages set status='trashed',trashed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP where id=?",(f.get('id'),));db.commit();audit('trash page',f.get('id',''));return go('/admin/pages')
        if f.get('action')=='restore':
            rev=db.execute('select * from page_revisions where page_id=? order by id desc limit 1',(f.get('id'),)).fetchone()
            if rev:
                snapshot=json.loads(rev['snapshot']); db.execute('update pages set title=?,slug=?,body=?,seo_title=?,meta_description=?,template=?,canonical_url=?,social_image=?,noindex=?,status=?,updated_at=CURRENT_TIMESTAMP,trashed_at=null where id=?',(snapshot['title'],snapshot['slug'],snapshot['body'],snapshot['seo_title'],snapshot['meta_description'],snapshot['template'],snapshot['canonical_url'],snapshot['social_image'],snapshot['noindex'],snapshot['status'],f.get('id')));db.commit();audit('restore page revision',f.get('id',''))
            return go('/admin/pages?edit='+str(f.get('id')))
        title=f.get('title','').strip(); slug=slugify(f.get('slug') or title); status=f.get('status','draft') if f.get('status') in STATUS else 'draft'
        try:sched=normalize_schedule(f.get('scheduled_at',''))
        except (ValueError,KeyError) as e:return page('Invalid schedule',f'<h1>{esc(e)}</h1>',True,'400 Bad Request')
        if old and old['slug']!=slug and old['status']=='published':add_slug_redirect(db,'/page/'+old['slug'],'/page/'+slug)
        try:
            if old:
                db.execute('insert into page_revisions(page_id,snapshot,editor) values(?,?,?)',(edit_id,json.dumps({k:old[k] for k in ('title','slug','body','seo_title','meta_description','template','canonical_url','social_image','noindex','status')}), user['username']))
                db.execute('update pages set title=?,slug=?,body=?,status=?,seo_title=?,meta_description=?,template=?,canonical_url=?,scheduled_at=?,social_image=?,noindex=?,updated_at=CURRENT_TIMESTAMP,trashed_at=case when ?="trashed" then CURRENT_TIMESTAMP else null end where id=?',(title,slug,f.get('body',''),status,f.get('seo_title',''),f.get('meta_description',''),f.get('template','general'),f.get('canonical_url',''),sched,f.get('social_image',''),bool_value(f,'noindex'),status,edit_id))
            else:db.execute('insert into pages(title,slug,body,status,seo_title,meta_description,template,canonical_url,scheduled_at,social_image,noindex) values(?,?,?,?,?,?,?,?,?,?,?)',(title,slug,f.get('body',''),status,f.get('seo_title',''),f.get('meta_description',''),f.get('template','general'),f.get('canonical_url',''),sched,f.get('social_image',''),bool_value(f,'noindex')))
            db.commit();audit('save page',title);return go('/admin/pages')
        except Exception as e:return page('Page save failed',f'<h1>Could not save page</h1><p>{esc(e)}</p>',True,'400 Bad Request')
    rows=db.execute('select * from pages order by updated_at desc').fetchall()
    values=dict(old) if old else {}; edit_form=form_start(csrf)+field('title','Title','text',values.get('title',''),True)+field('slug','Slug','text',values.get('slug',''))+field('body','Page content','textarea',values.get('body',''))+field('template','Template','select',values.get('template','general'),False,[(x,x.title()) for x in ('general','about','contact','legal','landing')])+field('status','Status','select',values.get('status','draft'),False,[(x,x.title()) for x in STATUS])+field('scheduled_at','Schedule ('+os.environ.get('BEYONDTOPIC_TIMEZONE','Asia/Kolkata')+')','datetime-local',display_schedule(values.get('scheduled_at')))+field('seo_title','SEO title','text',values.get('seo_title',''))+field('meta_description','Meta description','textarea',values.get('meta_description',''))+field('canonical_url','Canonical URL','url',values.get('canonical_url',''))+field('social_image','Social image URL','url',values.get('social_image',''))+field('noindex','Do not index this page','checkbox',values.get('noindex',0))+'<button>Save page</button></form>'
    if old:
        token=sign(str(old['id'])+':'+str(old['updated_at']))
        edit_form+=f'<p><a href="/preview-page/{old["id"]}?token={quote(token)}">Preview page</a></p>'+form_start(csrf)+f'<input type="hidden" name="id" value="{old["id"]}"><button name="action" value="restore">Restore prior revision</button></form>'+form_start(csrf)+f'<input type="hidden" name="id" value="{old["id"]}"><button class="secondary" name="action" value="duplicate">Duplicate page</button></form>'+form_start(csrf)+f'<input type="hidden" name="id" value="{old["id"]}"><button class="danger" name="action" value="trash">Move to trash</button></form>'
    rows_html=[]
    for x in rows:
        actions=form_start(csrf)+f'<input type="hidden" name="id" value="{x["id"]}"><button name="action" value="duplicate">Duplicate</button><button class="danger" name="action" value="trash">Trash</button></form>'
        rows_html.append([f'<a href="/admin/pages?edit={x["id"]}">{esc(x["title"])}</a>',esc(x['slug']),esc(x['status']),esc(x['updated_at']),actions])
    return page('Pages','<h1>Pages</h1><p>Published pages appear in the website footer. Privacy Policy and Terms and Conditions are live and editable here.</p>'+table(['Title','Slug','Status','Modified','Actions'],rows_html)+'<h2>'+('Edit page' if old else 'Create page')+'</h2>'+edit_form,True)

def manage_tags(db,method,f,query,csrf,page,go,audit):
    if method=='POST':
        tag_id=int(f.get('id') or 0)
        if f.get('action')=='merge':
            source=int(f.get('source_id','0'));target=int(f.get('target_id','0'))
            if not source or not target or source==target:return page('Choose two tags','<h1>Choose two different tags to merge.</h1>',True,'400 Bad Request')
            db.execute('insert or ignore into post_tags(post_id,tag_id) select post_id,? from post_tags where tag_id=?',(target,source));db.execute('delete from post_tags where tag_id=?',(source,));db.execute('delete from tags where id=?',(source,));db.commit();audit('merge tags',f'{source} into {target}');return go('/admin/tags')
        if f.get('action')=='delete':
            source=int(f.get('source_id','0'));db.execute('delete from post_tags where tag_id=?',(source,));db.execute('delete from tags where id=?',(source,));db.commit();audit('delete tag',str(source));return go('/admin/tags')
        name=f.get('name','').strip(); slug=slugify(f.get('slug') or name)
        try:
            if tag_id:db.execute('update tags set name=?,slug=? where id=?',(name,slug,tag_id))
            else:db.execute('insert or ignore into tags(name,slug) values(?,?)',(name,slug))
            db.commit();audit('save tag',name);return go('/admin/tags')
        except Exception as e:return page('Tag conflict',f'<h1>Could not save tag</h1><p>{esc(e)}</p>',True,'400 Bad Request')
    edit=int(query.get('edit',['0'])[0] or 0); current=db.execute('select * from tags where id=?',(edit,)).fetchone() if edit else None
    rows=db.execute('select t.*,count(pt.post_id) used from tags t left join post_tags pt on pt.tag_id=t.id group by t.id order by t.name').fetchall()
    form=form_start(csrf)+field('id','', 'hidden',current['id'] if current else '')+field('name','Tag name','text',current['name'] if current else '',True)+field('slug','Slug','text',current['slug'] if current else '')+'<button>Save tag</button></form>'
    rows_html=[]
    for x in rows:
        others=[(y['id'],y['name']) for y in rows if y['id']!=x['id']]
        actions=f'<a href="/admin/tags?edit={x["id"]}">Edit</a> '+form_start(csrf)+f'<input type="hidden" name="source_id" value="{x["id"]}">'+field('target_id','Merge into','select','',False,[('', '— choose —')]+others)+'<button name="action" value="merge">Merge</button><button class="danger" name="action" value="delete" onclick="return confirm(\'Delete this tag and remove it from stories?\')">Delete</button></form>'
        rows_html.append([esc(x['name']),esc(x['slug']),str(x['used']),actions])
    return page('Tags','<h1>Tags</h1>'+form+table(['Name','Slug','Stories','Actions'],rows_html),True)

def manage_authors(db,method,f,query,csrf,page,go,audit):
    edit=int(f.get('id') or query.get('edit',['0'])[0] or 0)
    current=db.execute('select * from authors where id=?',(edit,)).fetchone() if edit else None
    if method=='POST':
        photo=f.get('photo_media','').strip() or f.get('photo_url','').strip()
        if photo and not safe_profile_image(photo):return page('Invalid author photo','<h1>Choose an uploaded media image or enter an HTTPS photo URL.</h1>',True,'400 Bad Request')
        if photo.startswith('/media/') and not db.execute('select id from media where filename=?',(photo.rsplit('/',1)[-1],)).fetchone():return page('Author photo not found','<h1>Choose an image from the Media Library.</h1>',True,'400 Bad Request')
        vals=(f.get('name','').strip(),slugify(f.get('slug') or f.get('name')),f.get('bio',''),f.get('job_title',''),f.get('email',''),photo,f.get('social_links',''))
        if edit:db.execute('update authors set name=?,slug=?,bio=?,job_title=?,email=?,photo_url=?,social_links=? where id=?',vals+(edit,))
        else:db.execute('insert into authors(name,slug,bio,job_title,email,photo_url,social_links) values(?,?,?,?,?,?,?)',vals)
        db.commit();audit('save author',vals[0]);return go('/admin/authors')
    rows=db.execute('select a.*,count(p.id) posts from authors a left join posts p on p.author_id=a.id group by a.id order by a.name').fetchall()
    vals=dict(current) if current else {}
    media=db.execute('select filename,alt from media order by id desc').fetchall()
    media_options=[('', '— no uploaded photo —')]+[('/media/'+x['filename'],x['alt'] or x['filename']) for x in media]
    current_photo=vals.get('photo_url','')
    selected_media=current_photo if current_photo.startswith('/media/') else ''
    external_photo='' if selected_media else current_photo
    preview=f'<img class="author-photo-preview" src="{esc(current_photo)}" alt="Current author portrait">' if safe_profile_image(current_photo) else ''
    form=form_start(csrf)+field('id','', 'hidden',edit)+field('name','Name','text',vals.get('name',''),True)+field('slug','Slug','text',vals.get('slug',''))+field('job_title','Job title / role','text',vals.get('job_title',''))+field('bio','Biography','textarea',vals.get('bio',''))+preview+field('photo_media','Profile photo from Media Library','select',selected_media,False,media_options)+field('photo_url','Or enter profile photo URL','url',external_photo)+field('email','Public email (optional)','email',vals.get('email',''))+field('social_links','Social links (one URL per line)','textarea',vals.get('social_links',''))+'<button>Save author</button></form>'
    author_rows=[]
    for item in rows:
        avatar=f'<img src="{esc(item["photo_url"])}" alt="" class="author-list-avatar">' if safe_profile_image(item['photo_url']) else ''
        author_rows.append([f'<span class="author-admin-name">{avatar}{esc(item["name"])}</span>',esc(item['slug']),str(item['posts']),f'<a href="/admin/authors?edit={item["id"]}">Edit</a>'])
    return page('Authors','<h1>Authors</h1><p>Author profiles control the name, photo, role, biography, and links shown with their published stories.</p>'+form+table(['Author','Slug','Published posts','Action'],author_rows),True)

def manage_products(db,method,f,query,csrf,page,go,audit):
    edit=int(f.get('id') or query.get('edit',['0'])[0] or 0); current=db.execute('select * from products where id=?',(edit,)).fetchone() if edit else None
    if method=='POST':
        vals=(f.get('name','').strip(),f.get('brand',''),f.get('description',''),f.get('image_url',''),f.get('price',''),f.get('currency','USD'),f.get('merchant',''),f.get('destination_url',''),f.get('affiliate_url',''),f.get('market',''),bool_value(f,'active'))
        if not vals[0] or (vals[7] and not safe_external(vals[7])) or (vals[8] and not safe_external(vals[8])):return page('Invalid product','<h1>Product name and valid http(s) product URLs are required.</h1>',True,'400 Bad Request')
        if edit:db.execute('update products set name=?,brand=?,description=?,image_url=?,price=?,currency=?,merchant=?,destination_url=?,affiliate_url=?,market=?,active=? where id=?',vals+(edit,))
        else:db.execute('insert into products(name,brand,description,image_url,price,currency,merchant,destination_url,affiliate_url,market,active) values(?,?,?,?,?,?,?,?,?,?,?)',vals)
        db.commit();audit('save affiliate product',vals[0]);return go('/admin/products')
    rows=db.execute('select * from products order by name').fetchall()
    vals=dict(current) if current else {}
    form=form_start(csrf)+field('id','', 'hidden',edit)+field('name','Product name','text',vals.get('name',''),True)+field('brand','Brand','text',vals.get('brand',''))+field('description','Description','textarea',vals.get('description',''))+field('image_url','Image URL','url',vals.get('image_url',''))+field('price','Price','text',vals.get('price',''))+field('currency','Currency','text',vals.get('currency','USD'))+field('merchant','Merchant','text',vals.get('merchant',''))+field('destination_url','Original destination URL','url',vals.get('destination_url',''))+field('affiliate_url','Affiliate URL','url',vals.get('affiliate_url',''))+field('market','Country or market','text',vals.get('market',''))+field('active','Active','checkbox',vals.get('active',1))+'<button>Save product</button></form>'
    return page('Affiliate products','<h1>Affiliate products</h1>'+form+table(['Product','Brand','Merchant','Price','Status','Action'],[[esc(x['name']),esc(x['brand']),esc(x['merchant']),esc(x['price']+' '+x['currency']),('Active' if x['active'] else 'Inactive'),f'<a href="/admin/products?edit={x["id"]}">Edit</a>'] for x in rows]),True)

def manage_affiliate(db,method,f,query,csrf,page,go,audit):
    edit=int(f.get('id') or query.get('edit',['0'])[0] or 0);current=db.execute('select * from affiliate_links where id=?',(edit,)).fetchone() if edit else None
    if method=='POST':
        if not safe_external(f.get('destination','')) or not safe_external(f.get('affiliate_url','')):return page('Invalid URL','<h1>Use complete http or https URLs.</h1>',True,'400 Bad Request')
        vals=(f.get('name',''),f.get('merchant',''),f.get('destination',''),f.get('affiliate_url',''),f.get('campaign',''),int(f['product_id']) if f.get('product_id','').isdigit() else None,int(f['post_id']) if f.get('post_id','').isdigit() else None,bool_value(f,'active'))
        if edit:db.execute('update affiliate_links set name=?,merchant=?,destination=?,affiliate_url=?,campaign=?,product_id=?,post_id=?,active=?,updated_at=CURRENT_TIMESTAMP where id=?',vals+(edit,))
        else:db.execute('insert into affiliate_links(name,merchant,destination,affiliate_url,campaign,product_id,post_id,active,created_at,updated_at) values(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',vals)
        db.commit();audit('save affiliate link',f.get('name',''));return go('/admin/affiliate-links')
    products=options(db.execute('select id,name from products order by name').fetchall());posts=options(db.execute('select id,title name from posts order by title').fetchall())
    rows=db.execute('select l.*,p.name product from affiliate_links l left join products p on p.id=l.product_id order by l.id desc').fetchall()
    vals=dict(current) if current else {}
    form=form_start(csrf)+field('id','', 'hidden',edit)+field('name','Internal link name','text',vals.get('name',''),True)+field('merchant','Merchant','text',vals.get('merchant',''))+field('destination','Destination URL','url',vals.get('destination',''),True)+field('affiliate_url','Affiliate URL','url',vals.get('affiliate_url',''),True)+field('campaign','Campaign','text',vals.get('campaign',''))+field('product_id','Product','select',vals.get('product_id',''),False,products)+field('post_id','Associated story','select',vals.get('post_id',''),False,posts)+field('active','Active','checkbox',vals.get('active',1))+'<button>Save link</button></form>'
    return page('Affiliate links','<h1>Affiliate links</h1>'+form+table(['Name','Merchant','Product','Status','Affiliate URL','Action'],[[esc(x['name']),esc(x['merchant']),esc(x['product']),('Active' if x['active'] else 'Inactive'),esc(x['affiliate_url']),f'<a href="/admin/affiliate-links?edit={x["id"]}">Edit</a>'] for x in rows]),True)

def manage_redirects(db,method,f,query,csrf,page,go,audit):
    if method=='POST':
        rid=int(f.get('id') or 0)
        if f.get('action')=='toggle':
            db.execute('update redirects set active=1-active where id=?',(f.get('id'),));db.commit();audit('toggle redirect',f.get('id',''));return go('/admin/redirects')
        if f.get('action')=='delete':
            db.execute('delete from redirects where id=?',(f.get('id'),));db.commit();audit('delete redirect',f.get('id',''));return go('/admin/redirects')
        source=f.get('source','').strip();dest=f.get('destination','').strip();code=int(f.get('code','301'))
        if not source.startswith('/') or source.startswith('//') or not dest.startswith('/') or dest.startswith('//') or source==dest or code not in (301,302) or redirect_loops(db,source,dest):return page('Redirect invalid','<h1>Use local paths only, a valid 301/302, and no redirect loops.</h1>',True,'400 Bad Request')
        try:
            if rid:db.execute('update redirects set source=?,destination=?,code=?,active=?,notes=? where id=?',(source,dest,code,bool_value(f,'active'),f.get('notes',''),rid))
            else:db.execute('insert into redirects(source,destination,code,active,notes) values(?,?,?,?,?)',(source,dest,code,bool_value(f,'active'),f.get('notes','')))
            db.commit();audit('save redirect',source);return go('/admin/redirects')
        except Exception as e:return page('Redirect conflict',f'<h1>Redirect already exists or invalid</h1><p>{esc(e)}</p>',True,'400 Bad Request')
    edit=int(query.get('edit',['0'])[0] or 0);current=db.execute('select * from redirects where id=?',(edit,)).fetchone() if edit else None;values=dict(current) if current else {}
    rows=db.execute('select * from redirects order by id desc').fetchall();form=form_start(csrf)+field('id','', 'hidden',edit)+field('source','Source path','text',values.get('source',''),True)+field('destination','Destination path','text',values.get('destination',''),True)+field('code','Type','select',str(values.get('code',301)),False,[('301','301 permanent'),('302','302 temporary')])+field('notes','Notes','textarea',values.get('notes',''))+field('active','Active','checkbox',values.get('active',1))+'<button>Save redirect</button></form>'
    actions=[]
    for x in rows:
        action=form_start(csrf)+f'<a href="/admin/redirects?edit={x["id"]}">Edit</a><input type="hidden" name="id" value="{x["id"]}"><button name="action" value="toggle">{("Disable" if x["active"] else "Enable")}</button><button class="danger" name="action" value="delete" onclick="return confirm(\'Delete this redirect?\')">Delete</button></form>'
        actions.append([esc(x['source']),esc(x['destination']),str(x['code']),('Active' if x['active'] else 'Inactive'),esc(x['notes']),action])
    return page('Redirects','<h1>Redirects</h1>'+form+table(['Source','Destination','Code','Status','Notes','Actions'],actions),True)

def manage_navigation(db,method,f,query,csrf,page,go,audit):
    if method=='POST':
        if f.get('delete'):
            db.execute('delete from menu_items where id=?',(int(f['delete']),));db.commit();audit('remove navigation item',f['delete']);return go('/admin/navigation')
        item_id=int(f.get('id') or 0)
        if f.get('action')=='toggle':db.execute('update menu_items set active=1-active where id=?',(f.get('id'),));db.commit();audit('toggle navigation item',f.get('id',''));return go('/admin/navigation')
        url=f.get('url','/').strip()
        if not (url.startswith('/') and not url.startswith('//')) and not safe_external(url):return page('Invalid menu URL','<h1>Menu links must use a local path or a complete http(s) URL.</h1>',True,'400 Bad Request')
        vals=(f.get('label',''),url,int(f.get('position','0') or 0),bool_value(f,'active'))
        if item_id:db.execute('update menu_items set label=?,url=?,position=?,active=? where id=?',vals+(item_id,))
        else:db.execute('insert into menu_items(label,url,position,active) values(?,?,?,?)',vals)
        db.commit();audit('save navigation item',f.get('label',''));return go('/admin/navigation')
    edit=int(query.get('edit',['0'])[0] or 0);current=db.execute('select * from menu_items where id=?',(edit,)).fetchone() if edit else None;values=dict(current) if current else {}
    rows=db.execute('select * from menu_items order by position,id').fetchall()
    form=form_start(csrf)+field('id','', 'hidden',edit)+field('label','Label','text',values.get('label',''),True)+field('url','URL','text',values.get('url','/'),True)+field('position','Position','number',values.get('position','0'))+field('active','Enabled','checkbox',values.get('active',1))+'<button>Save menu item</button></form>'
    actions=[[esc(x['label']),esc(x['url']),str(x['position']),('Enabled' if x['active'] else 'Hidden'),f'<a href="/admin/navigation?edit={x["id"]}">Edit</a> '+form_start(csrf)+f'<input type="hidden" name="id" value="{x["id"]}"><button name="action" value="toggle">Toggle</button><button name="delete" value="{x["id"]}">Remove</button></form>'] for x in rows]
    return page('Navigation','<h1>Navigation</h1>'+form+table(['Label','URL','Position','Status','Action'],actions),True)

def manage_homepage(db,method,f,query,csrf,page,go,audit):
    if method=='POST':
        action=f.get('action','save');section_id=int(f.get('id') or 0)
        if action=='toggle':db.execute('update homepage_sections set enabled=1-enabled where id=?',(section_id,))
        elif action=='delete':db.execute('delete from homepage_sections where id=?',(section_id,))
        elif action in ('move_up','move_down'):
            ordered=list(db.execute('select id,position from homepage_sections order by position,id'))
            ids=[x['id'] for x in ordered]
            if section_id in ids:
                index=ids.index(section_id);other=index+(-1 if action=='move_up' else 1)
                if 0<=other<len(ids):
                    ordered[index],ordered[other]=ordered[other],ordered[index]
                    for position,item in enumerate(ordered):db.execute('update homepage_sections set position=? where id=?',(position*10,item['id']))
        else:
            title=f.get('title','').strip();kind=f.get('section_type','latest');position=int(f.get('position','0') or 0)
            valid={'latest'}|{'category:'+x['slug'] for x in db.execute('select slug from categories where active=1')}
            if not title or kind not in valid:return page('Invalid section','<h1>Enter a section heading and choose an active source.</h1>',True,'400 Bad Request')
            if section_id:db.execute('update homepage_sections set title=?,section_type=?,position=?,enabled=? where id=?',(title,kind,position,bool_value(f,'enabled'),section_id))
            else:db.execute('insert into homepage_sections(title,section_type,position,enabled) values(?,?,?,?)',(title,kind,position,bool_value(f,'enabled')))
        db.commit();audit('update homepage sections',f.get('title',action));return go('/admin/homepage')
    cats=[('latest','Latest stories')]+[('category:'+x['slug'],x['name']) for x in db.execute('select * from categories order by name')]
    edit=int(query.get('edit',['0'])[0] or 0);current=db.execute('select * from homepage_sections where id=?',(edit,)).fetchone() if edit else None
    vals=dict(current) if current else {}
    form=form_start(csrf)+field('id','', 'hidden',edit)+field('title','Section heading','text',vals.get('title',''),True)+field('section_type','Content source','select',vals.get('section_type','latest'),True,cats)+field('position','Display order','number',vals.get('position',0))+field('enabled','Show on homepage','checkbox',vals.get('enabled',1))+f'<button>{"Save changes" if current else "Add section"}</button></form>'
    rows=db.execute('select * from homepage_sections order by position').fetchall()
    actions=[]
    for x in rows:
        controls=form_start(csrf)+f'<input type="hidden" name="id" value="{x["id"]}"><a href="/admin/homepage?edit={x["id"]}">Edit</a> <button name="action" value="move_up" aria-label="Move {esc(x["title"])} up">↑</button> <button name="action" value="move_down" aria-label="Move {esc(x["title"])} down">↓</button> <button name="action" value="toggle">{"Disable" if x["enabled"] else "Enable"}</button> <button name="action" value="delete" onclick="return confirm(&quot;Remove this homepage section?&quot;)">Remove</button></form>'
        actions.append([esc(x['title']),esc(x['section_type']),str(x['position']),('Shown' if x['enabled'] else 'Hidden'),controls])
    return page('Homepage builder','<p class="eyebrow">PUBLICATION DESIGN</p><h1>Homepage builder</h1><p>Arrange the homepage, choose its content sources, and hide sections that are not ready to publish. Only published stories appear.</p>'+form+'<h2>Current sections</h2>'+table(['Section','Content source','Order','Visibility','Actions'],actions),True)

AD_SLOTS={
    'home_after_hero':'Homepage · below the hero',
    'home_after_stories':'Homepage · between stories and newsletter',
    'story_after_image':'Story · below the featured image',
    'story_after_article':'Story · after the article',
}
def ad_banner(db,slot):
    vals={x['key'].split('.',2)[2]:x['value'] for x in db.execute('select key,value from settings where key like ?',('ads.'+slot+'.%',))}
    image=vals.get('image','').strip(); destination=vals.get('url','').strip()
    if vals.get('enabled')!='1' or not image:return ''
    if not safe_profile_image(image):return ''
    if destination and not (destination.startswith('/') and not destination.startswith('//')) and not safe_external(destination):destination=''
    visual=f'<img src="{esc(image)}" alt="{esc(vals.get("alt") or vals.get("name") or "Sponsored advertisement")}" loading="lazy">'
    if destination:visual=f'<a href="{esc(destination)}" rel="sponsored nofollow noopener"'+(' target="_blank"' if safe_external(destination) else '')+'>'+visual+'</a>'
    return f'<aside class="ad-banner" aria-label="Advertisement"><div class="ad-banner-label">Advertisement</div>{visual}{("<p>"+esc(vals.get("name",""))+"</p>") if vals.get("name") else ""}</aside>'

def manage_advertising(db,method,f,csrf,page,go,audit):
    if method=='POST':
        slot=f.get('slot','')
        if slot not in AD_SLOTS:return page('Invalid ad placement','<h1>Choose a valid ad placement.</h1>',True,'400 Bad Request')
        image=f.get('image','').strip();url=f.get('url','').strip()
        if image and not safe_profile_image(image):return page('Invalid image URL','<h1>Use an http(s) image URL or an uploaded image path from the media library.</h1><p><a href="/admin/advertising">Return to advertising placements</a></p>',True,'400 Bad Request')
        if url and not (url.startswith('/') and not url.startswith('//')) and not safe_external(url):return page('Invalid destination','<h1>Use a local path or a complete http(s) destination URL.</h1><p><a href="/admin/advertising">Return to advertising placements</a></p>',True,'400 Bad Request')
        values={'name':f.get('name','').strip(),'image':image,'alt':f.get('alt','').strip(),'url':url,'enabled':'1' if bool_value(f,'enabled') else '0'}
        for key,value in values.items():db.execute('insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value',(f'ads.{slot}.{key}',value))
        db.commit();audit('update ad placement',AD_SLOTS[slot]);return go('/admin/advertising')
    saved={x['key']:x['value'] for x in db.execute("select key,value from settings where key like 'ads.%'")}
    cards=[]
    for slot,title in AD_SLOTS.items():
        prefix='ads.'+slot+'.';name=saved.get(prefix+'name','');image=saved.get(prefix+'image','');alt=saved.get(prefix+'alt','');url=saved.get(prefix+'url','');enabled=saved.get(prefix+'enabled','0')=='1'
        preview=ad_banner(db,slot) or '<div class="ad-preview-empty">No banner is live in this placement.</div>'
        form=form_start(csrf)+f'<input type="hidden" name="slot" value="{slot}"><h2>{esc(title)}</h2><p>Recommended image: 1200 × 300 px. Keep the artwork readable on mobile.</p>'+field('name','Advertiser or campaign name','text',name)+field('image','Banner image URL or uploaded /media/... path','url' if image.startswith('http') else 'text',image)+field('alt','Image description','text',alt)+field('url','Click-through destination (local path or https URL)','url' if url.startswith('http') else 'text',url)+field('enabled','Show this advertisement','checkbox',enabled)+'<button>Save placement</button></form>'
        cards.append(f'<section class="ad-placement"><div>{form}</div><div class="ad-placement-preview"><p class="eyebrow">LIVE PREVIEW</p>{preview}</div></section>')
    note='<p class="notice">Banners are image based and clearly labeled as advertisements. Upload artwork in Media, then paste its /media/... path here. This keeps third-party ad scripts out of the site.</p>'
    return page('Advertising placements','<p class="eyebrow">SPONSORSHIP STUDIO</p><h1>Advertising placements</h1><p>Set a separate banner, destination, and visibility for each position. Saved banners appear on the public pages immediately.</p>'+note+''.join(cards),True)

def manage_settings(db,method,f,csrf,page,go,audit,group):
    if method=='POST':
        for key,value in f.items():
            if key!='csrf':db.execute('insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value',(group+'.'+key,value))
        db.commit();audit('update '+group+' settings');return go('/admin/'+('seo' if group=='seo' else 'settings'))
    vals={x['key'].split('.',1)[-1]:x['value'] for x in db.execute('select * from settings where key like ?', (group+'.%',))}
    form=form_start(csrf)
    fields=[('site_title','Site title'),('tagline','Tagline'),('contact_email','Contact email'),('social_links','Social links (one per line)')] if group=='site' else [('default_title','Default SEO title'),('default_description','Default meta description'),('canonical_base','Canonical site URL'),('default_noindex','Default noindex (true/false)')]
    for key,label in fields:form+=field(key,label,'textarea' if 'links' in key or 'description' in key else 'text',vals.get(key,''))
    return page('Website settings' if group=='site' else 'SEO settings',f'<h1>{"Website settings" if group=="site" else "SEO settings"}</h1>{form}<button>Save settings</button></form>',True)

def manage_users(db,method,f,user,csrf,page,go,audit):
    if method=='POST':
        if f.get('action')=='delete':
            target=db.execute('select id,username from users where id=?',(f.get('id'),)).fetchone()
            if not target or target['username']==user['username'] or db.execute('select count(*) from users where role="admin"').fetchone()[0]<2:return page('Cannot remove account','<h1>Keep at least one administrator and do not remove your active account.</h1>',True,'400 Bad Request')
            db.execute('delete from users where id=?',(target['id'],));db.commit();audit('delete user',target['username']);return go('/admin/users')
        name=f.get('username','').strip();password=f.get('password','');role=f.get('role','author')
        if len(password)<12 or role not in ('admin','editor','author','contributor','seo_manager','affiliate_manager'):return page('Invalid account','<h1>Choose a role and use a password of at least 12 characters.</h1>',True,'400 Bad Request')
        author_id=int(f['author_id']) if role in ('author','contributor') and f.get('author_id','').isdigit() else None
        if role in ('author','contributor') and not author_id:return page('Author profile required','<h1>Select the public author profile for this account.</h1>',True,'400 Bad Request')
        db.execute('insert into users(username,password_hash,role,author_id) values(?,?,?,?)',(name,password_hash(password),role,author_id));db.commit();audit('create user',name);return go('/admin/users')
    authors=options(db.execute('select id,name from authors order by name').fetchall())
    roles=('admin','editor','author','contributor','seo_manager','affiliate_manager')
    form=form_start(csrf)+field('username','Username','text','',True)+field('password','Temporary password (12+ characters)','password','',True)+field('role','Role','select','author',False,[(x,x.replace('_',' ').title()) for x in roles])+field('author_id','Linked public author profile (required for Author or Contributor)','select','','',authors)+'<button>Create user</button></form>'
    rows=db.execute('select * from users order by username').fetchall()
    return page('Users and roles','<h1>Users and roles</h1>'+form+table(['Username','Role','Action'],[[esc(x['username']),esc(x['role']),form_start(csrf)+f'<input type="hidden" name="action" value="delete"><button name="id" value="{x["id"]}">Remove</button></form>'] for x in rows]),True)

def manage_media(db,environ,method,f,query,csrf,page,go,audit):
    if method=='POST':
        if isinstance(f,cgi.FieldStorage):
            file=f['file'] if 'file' in f else None
            if not file or not getattr(file,'file',None):return page('Choose a file','<h1>Select an image file.</h1>',True,'400 Bad Request')
            data=file.file.read(5*1024*1024+1); filename=os.path.basename(file.filename or '')
            suffix=Path(filename).suffix.lower(); allowed={'.jpg','.jpeg','.png','.gif','.webp'}; suffix='.jpg' if suffix=='.jpeg' else suffix
            if len(data)>5*1024*1024 or suffix not in allowed or not valid_image(data,suffix):return page('Invalid media','<h1>Use a JPG, PNG, GIF, or WebP image under 5 MB.</h1>',True,'400 Bad Request')
            stored=secrets.token_hex(16)+suffix;MEDIA_DIR.mkdir(parents=True,exist_ok=True);(MEDIA_DIR/stored).write_bytes(data)
            db.execute('insert into media(filename,alt,caption,description,mime_type,size) values(?,?,?,?,?,?)',(stored,f.getfirst('alt',''),f.getfirst('caption',''),f.getfirst('description',''),mimetypes.guess_type(stored)[0] or 'image/jpeg',len(data)));db.commit();audit('upload media',stored);return go('/admin/media')
        item_id=int(f.get('id','0') or 0)
        db.execute('update media set alt=?,caption=?,description=? where id=?',(f.get('alt',''),f.get('caption',''),f.get('description',''),item_id));db.commit();audit('update media details',str(item_id));return go('/admin/media')
    term=query.get('q',[''])[0].strip()
    rows=db.execute('select * from media where filename like ? or alt like ? or caption like ? order by id desc',('%'+term+'%',)*3).fetchall()
    form=form_start(csrf,multipart=True)+field('file','Image (5 MB maximum)','file','',True)+field('alt','Alt text','text','',True)+field('caption','Caption')+field('description','Description','textarea')+'<button>Upload image</button></form>'
    search='<form class="filters"><input name="q" value="'+esc(term)+'" placeholder="Search filenames and alt text"><button>Search media</button></form>'
    cards=''.join(f'<article class="card"><img class="media-thumb" src="/media/{quote(x["filename"])}" alt="{esc(x["alt"])}"><b>{esc(x["filename"])}</b><p>{x["size"]} bytes · {esc(x["mime_type"])}</p><code>/media/{esc(x["filename"])}</code>'+form_start(csrf)+f'<input type="hidden" name="id" value="{x["id"]}">'+field('alt','Alt text','text',x['alt'],True)+field('caption','Caption','text',x['caption'])+field('description','Description','textarea',x['description'])+'<button>Save details</button></form></article>' for x in rows)
    return page('Media library','<h1>Media library</h1><p>Only validated raster images are accepted; unused-file detection is manual.</p>'+form+search+'<div class="grid">'+cards+'</div>',True)
def valid_image(data,suffix):
    return (suffix in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8\xff')) or (suffix=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or (suffix=='.gif' and data[:6] in (b'GIF87a',b'GIF89a')) or (suffix=='.webp' and data[:4]==b'RIFF' and data[8:12]==b'WEBP')
def admin_subscribers(db,page):
    rows=db.execute('select email,status,consent_at,created_at from subscribers order by created_at desc').fetchall()
    return page('Subscribers','<p class="eyebrow">AUDIENCE</p><h1>Newsletter subscribers</h1><p>Email delivery requires a provider; consent, subscription status, and unsubscribe requests are stored locally.</p><p><a class="button" href="/admin/subscribers/export.csv">Export CSV</a></p>'+table(['Email','Status','Consent recorded','Joined'],[[esc(x['email']),esc(x['status']),esc(x['consent_at'] or '—'),esc(x['created_at'])] for x in rows]),True)
def audit_view(db,limit=10):return table(['User','Action','Detail','Time'],[[esc(x['username']),esc(x['action']),esc(x['detail']),esc(x['created_at'])] for x in db.execute('select * from audit_logs order by id desc limit ?',(limit,))])

def initialize_site_data():
    database.initialize()
    with database.connect() as db:
        if not db.execute('select id from users limit 1').fetchone():
            username=os.environ.get('BEYONDTOPIC_ADMIN','admin'); password=os.environ.get('BEYONDTOPIC_PASSWORD')
            if not password:
                password=secrets.token_urlsafe(18)
                if not os.environ.get('VERCEL'):print(f'First-run admin password: {password}')
            db.execute('insert into users(username,password_hash,role) values(?,?,?)',(username,password_hash(password),'admin'))
        if not db.execute('select id from authors limit 1').fetchone():db.execute("insert into authors(name,slug,bio) values('BeyondTopic Editors','editors','Independent editors exploring what matters.')")
        seeds={'Fashion':['Trends','Outfit Ideas','Seasonal Fashion','Accessories','Footwear','Shopping Guides'],'Lifestyle':['Daily Living','Relationships','Personal Development','Home and Living','Entertainment','Culture'],'Travel':['Destinations','Travel Guides','Hotels and Resorts','Budget Travel','Luxury Travel','Travel Tips','Itineraries'],'Beauty':['Skincare','Haircare','Makeup','Beauty Products','Beauty Guides'],'Shopping':['Buying Guides','Product Comparisons','Best Products','Seasonal Shopping','Gift Guides','Deals and Offers'],'Technology':['Gadgets','Apps and Software','Consumer Technology','Product Reviews','How-to Guides'],'Wellness':['Fitness','Everyday Wellness','Healthy Habits']}
        for name,children in seeds.items():
            slug=slugify(name);db.execute('insert or ignore into categories(name,slug) values(?,?)',(name,slug));parent=db.execute('select id from categories where slug=?',(slug,)).fetchone()['id']
            for child in children:db.execute('insert or ignore into categories(name,slug,parent_id) values(?,?,?)',(child,slugify(child),parent))
        category_descriptions={'fashion':'Personal style, thoughtful wardrobes, and the ideas shaping what we wear.','lifestyle':'Considered ideas for living well at home, at work, and in the everyday.','travel':'Places to discover and practical ways to plan a more thoughtful journey.','beauty':'Clear, personal perspectives on skincare, hair, makeup, and everyday beauty.','shopping':'Useful buying guides that put needs, trade-offs, and thoughtful choices first.','technology':'Approachable guides to the devices, software, and digital habits in daily life.','wellness':'Gentle, practical ideas for movement, rest, and everyday wellbeing.'}
        for slug,description in category_descriptions.items():db.execute('update categories set description=? where slug=? and trim(description)=""',(description,slug))
        default_pages={'About BeyondTopic':'about','Contact':'contact','Editorial Policy':'editorial-policy','Privacy Policy':'privacy-policy','Terms and Conditions':'terms-and-conditions','Affiliate Disclosure':'affiliate-disclosure','Cookie Policy':'cookie-policy','Advertise With Us':'advertise-with-us'}
        for title,slug in default_pages.items():db.execute('insert or ignore into pages(title,slug,status,template) values(?,?,?,?)',(title,slug,'draft','legal' if 'Policy' in title or title.startswith('Terms') else 'general'))
        if not db.execute("select value from settings where key='starter_pages_version'").fetchone():
            starter_pages={
              'about':('About BeyondTopic','BeyondTopic is an independent publication for everyday curiosity. We explore personal style, travel, beauty, shopping, technology, wellness, and the small choices that make a life feel more considered.\n\nOur aim is to make useful, readable stories that help people explore a subject and make up their own minds. The publication is being built from the ground up; the starter stories on this site are clearly labelled and are here to demonstrate the editorial experience.\n\nWe do not claim tests, reporting, endorsements, or credentials that have not happened. As BeyondTopic grows, this page and our editorial standards will grow with it.'),
              'editorial-policy':('Editorial Policy','BeyondTopic is an independent editorial project. We aim to publish original, useful information in clear language and to distinguish editorial judgment from commercial relationships.\n\nStarter stories are labeled in the article and should be reviewed and rewritten by the publisher before they are treated as finished editorial work. Product prices, availability, travel details, and other changeable information should be checked with current primary sources before publication.\n\nWhen we make a material correction or update to a published story, we aim to update the article and its date so readers can see that the information changed.'),
              'affiliate-disclosure':('Affiliate Disclosure','Some future BeyondTopic stories may include affiliate links. If you buy through an eligible link, BeyondTopic may receive a commission at no extra cost to you. We will identify affiliate content in the article where it appears.\n\nA commission does not mean a product has been tested, reviewed, or endorsed. Starter buying guides and sample product copy are illustrative and do not represent verified recommendations, prices, or offers. Check current product details with the seller before purchasing.')}
            for slug,(title,body) in starter_pages.items():db.execute("update pages set body=?,status='published',updated_at=CURRENT_TIMESTAMP where slug=? and status='draft' and trim(body)=''",(body,slug))
            db.execute("insert into settings(key,value) values('starter_pages_version','1')")
        policy_starters={
          'privacy-policy':('Privacy Policy',"""Last updated: October 9, 2026

This notice explains how BeyondTopic handles information when you read this publication or subscribe to its newsletter. It is a plain-language starting policy for this site; the publisher should review it for the laws and services that apply before a public launch.

## Information we handle

If you subscribe, the site stores your email address, subscription status, and the time you gave consent. Unsubscribe requests are recorded so that your preference can be respected. The local preview currently records subscriptions but does not send newsletter email.

Publisher accounts use a username and a securely hashed password. Editors may also add articles, page content, and images to the publication. The site may record basic technical and security events needed to run and protect the service, and records when a reader follows an affiliate link.

## How information is used

Information is used to operate and secure the publication, manage newsletter preferences, maintain the editorial site, and understand limited interactions such as affiliate-link clicks. This version does not have a visitor analytics provider or advertising-tracking service configured.

## Cookies and external services

The site uses essential cookies for form security and publisher sign-in. No optional advertising or cross-site tracking cookies are configured in this local version. Story images may be served by Unsplash, and links may take you to third-party sites; those services have their own privacy practices.

## Storage, access, and your choices

Information is stored in the publication’s local database and is available to authorized publishers who operate the site. The publisher should keep access limited, protect backups, and remove information when it is no longer needed, subject to applicable record-keeping requirements. You can use the unsubscribe link in a newsletter message when email delivery is enabled. For questions or requests about personal information, contact the publisher using the email shown in the site footer. The publisher should add a monitored email under Admin → Settings before launch.

## Children and changes

This publication is intended for a general audience and is not designed to collect information from children. The publisher may update this notice when site features or practices change; the current version will appear on this page."""),
          'terms-and-conditions':('Terms and Conditions',"""Last updated: October 9, 2026

These terms apply when you browse BeyondTopic. By using the site, you agree to use it lawfully and respectfully. The publisher should review these starter terms for the laws and services that apply before a public launch.

## Editorial information

BeyondTopic publishes general-interest articles and guides. Content is provided for information and entertainment; it is not medical, legal, financial, travel-safety, or other professional advice. Details such as prices, availability, product specifications, schedules, and local requirements can change, so verify them with an appropriate current source before acting.

Some stories are labeled as starter content. These examples are provided to demonstrate the publication and should not be treated as independently reported, tested, or verified recommendations. The publisher may update, correct, or remove content at any time.

## Your use of the site

You may read and share links to public pages. Unless the publisher gives permission or applicable law allows it, do not republish substantial site content, misuse images, interfere with the site, attempt unauthorized access, or use the site to distribute harmful or unlawful material.

## Intellectual property and third-party links

Site text, branding, and original materials belong to their respective rights holders. Image credits and third-party materials remain with their owners. Links to external sites are provided for convenience; BeyondTopic does not control or guarantee their content, products, or services.

Some links may be affiliate links. If you purchase through an eligible link, the publication may earn a commission at no additional cost to you. Affiliate relationships are disclosed where relevant and do not guarantee a review or endorsement.

## Availability and liability

The site is provided as available. To the extent permitted by applicable law, the publisher makes no guarantee that the site or its content will always be complete, current, uninterrupted, or error-free, and is not responsible for losses arising from reliance on general site content or third-party services. Nothing in these terms limits rights or remedies that cannot legally be limited.

## Changes and contact

The publisher may revise these terms as the publication changes. Updated terms will be posted on this page. For questions, contact the publisher using the email shown in the site footer. The publisher should add a monitored email under Admin → Settings before launch.""")
        }
        for slug,(title,body) in policy_starters.items():
            db.execute("update pages set title=?,body=?,status='published',template='legal',updated_at=CURRENT_TIMESTAMP where slug=? and status='draft' and trim(body)=''",(title,body,slug))
        db.execute('insert or ignore into settings(key,value) values(?,?)',('site.title','BeyondTopic'));db.commit()
        if not db.execute("select value from settings where key='demo_seed_version'").fetchone() or db.execute("select value from settings where key='demo_seed_version'").fetchone()['value']<'3':
            samples=[
              ('Sample: Building a More Considered Wardrobe','fashion','A practical framework for choosing fewer pieces and making them work harder.','DEMO CONTENT — This example is illustrative and is not reported fashion advice.\n\n# Start with what you wear\nNotice the pieces you reach for most often. A useful wardrobe begins with your actual routines, climate, and comfort.\n\n## Try a small palette\nChoose a few colors that already appear in your closet, then use them to guide future purchases.\n\n- Repair and restyle before replacing\n- Check fit and fabric in natural light\n- Keep a short list of gaps'),
              ('Sample: A Calmer Weekly Reset','lifestyle','A gentle planning ritual designed to leave room for real life.','DEMO CONTENT — A sample lifestyle story for demonstrating the editor.\n\n# Make a little space\nPick one small surface or routine to reset. A short, repeatable practice is easier to keep than an ambitious overhaul.\n\n## Keep the plan flexible\nList the essentials first, then leave unscheduled time for rest, changes, and the unexpected.'),
              ('Sample: A Slow Weekend in Kyoto','travel','A sample itinerary that favors neighborhood walks and unhurried stops.','DEMO CONTENT — This is a fictional planning example. Verify current opening hours, transport, and travel requirements before planning a trip.\n\n# Begin with a neighborhood\nChoose one area for the morning and explore on foot. A slower route can leave room for a cafe, a garden, or an unexpected turn.\n\n## Check details before you go\nTransit routes and venue schedules change. Confirm details with official local sources.'),
              ('Sample: How to Compare Everyday Carry-On Bags','shopping','A buying-guide framework based on fit, access, durability, and warranty.','DEMO CONTENT — No products, prices, or retailer claims have been independently tested.\n\n# Compare the basics\nStart with the airline and trip lengths you actually use. Then compare dimensions, empty weight, wheel quality, handle comfort, and repair support.\n\n> Treat listed dimensions as a starting point and verify them with the carrier.'),
              ('Sample: A Simple Product Comparison Framework','shopping','A transparent checklist for comparing products without relying on marketing claims.','DEMO CONTENT — Illustrative buying guide; it does not rate or endorse real products.\n\n# Set your requirements\nWrite down what the item needs to do, your budget, and the compromises you can accept.\n\n## Compare like with like\nUse the same criteria for each option and distinguish measured specifications from opinions.'),
              ('Sample: What to Check Before Installing a New App','technology','A plain-language checklist for evaluating permissions, updates, and data settings.','DEMO CONTENT — General educational example, not a review of a specific app.\n\n# Review permissions\nAsk whether each permission is needed for the feature you want. Check the publisher and update history before installing.\n\n## Revisit privacy settings\nApp settings and policies change. Review current controls directly in the app and its official documentation.')]
            extras={
              'fashion':['Three Ways to Build a More Versatile Capsule','The Art of Getting Dressed in Layers','A Fabric Guide for Everyday Clothes','How to Shop Your Closet First'],
              'lifestyle':['A Room-by-Room Guide to a Softer Home','Small Rituals That Make Mornings Easier','How to Make Space for a New Hobby','A Practical Guide to a Digital Reset'],
              'travel':['A Thoughtful Guide to Planning a City Break','What to Pack for a Long Weekend','How to Find Your Rhythm in a New Place','A Field Guide to Scenic Train Travel'],
              'beauty':['A Gentle Guide to Building a Skincare Routine','What to Look for on a Beauty Label','A Low-Fuss Haircare Routine for Busy Weeks','Makeup Essentials for a Small Kit','How to Introduce a New Skincare Product'],
              'shopping':['A Reusable Checklist for Smarter Shopping','How to Read Product Reviews with Care','A Gift Guide for People Who Value Useful Things'],
              'technology':['A Friendly Guide to a Less Distracting Phone','How to Choose the Right Headphones for You','A Home Office Setup That Works Harder','Simple Steps to Organize Your Digital Photos'],
              'wellness':['A Gentle Stretch Break for Desk Days','How to Build a Walking Habit That Lasts','A Beginner’s Guide to Restful Evenings','Making Movement Fit Into a Busy Week','A Simple Way to Notice Your Energy']}
            descriptions={
              'fashion':('Begin with the pieces, colors, and proportions you already enjoy. A practical wardrobe reflects its owner’s real days.','Try one small change at a time: repeat a favorite silhouette, add a useful layer, or repair a well-loved piece. Personal comfort is a better guide than a passing trend.'),
              'lifestyle':('Choose a small change that solves a real daily friction point. A room or routine does not need a full makeover to feel more considered.','Start with what you use, then leave space for the objects and rituals that make the place feel personal. Make adjustments gradually and keep the parts that work.'),
              'travel':('A rewarding trip starts with a flexible plan and room for the unexpected. Use this sample as a starting point, and check current local details before you go.','Pick one anchor for the day, map a simple route, and save a few optional stops. Confirm transport, opening hours, accessibility, and entry requirements with official sources.'),
              'beauty':('A useful routine can be simple and personal. Consider your preferences, sensitivities, and the guidance on product labels before changing what you use.','Introduce one new product at a time and follow its directions. For persistent irritation or specific skin concerns, consult a qualified clinician.'),
              'shopping':('The best choice depends on how you will use an item, what matters to you, and the trade-offs you are willing to make.','Set your must-haves before comparing options. Check current specifications, warranty terms, return policies, and independent sources; details can change.'),
              'technology':('A few thoughtful settings can make everyday technology feel more intentional. Names and options vary across devices, so consult the manufacturer’s current support guidance.','Start with the setting that addresses your biggest distraction or privacy concern. Change one thing at a time and check that the result suits your needs.'),
              'wellness':('Small, comfortable routines can be easier to return to than ambitious plans. Adapt any movement or habit to your own ability and circumstances.','Keep the first step gentle and specific. If an activity causes pain or a health concern, stop and seek appropriate professional advice.')}
            for cat,titles in extras.items():
                for title in titles:
                    intro,advice=descriptions[cat]
                    samples.append((f'Sample: {title}',cat,intro,f'DEMO CONTENT — An illustrative BeyondTopic sample article. This is general editorial information, not individualized professional advice.\n\n# Begin with what matters to you\n{intro}\n\n## Make a useful first step\n{advice}\n\n## Keep the approach flexible\nNotice what works in your circumstances and adjust as needed. Check current, authoritative sources whenever details may change.'))
            photos={
              'fashion':[('photo-1483985988355-763728e1935b','A thoughtful wardrobe being explored in a clothing shop'),('photo-1490481651871-ab68de25d43d','Carefully selected pieces and accessories'),('photo-1539109136881-3be0616acf4b','Contemporary street style in the city'),('photo-1529139574466-a303027c1d8b','Modern fashion editorial portrait'),('photo-1515886657613-9f3515b0c78f','A considered everyday outfit outdoors')],
              'lifestyle':[('photo-1497366754035-f200968a6e72','A calm, light-filled workspace'),('photo-1616486338812-3dadae4b4ace','Thoughtful neutral living room details'),('photo-1618220179428-7757a8c0b2f5','A welcoming modern home interior'),('photo-1600210492486-724fe5c67fb0','Warm, understated home furnishings'),('photo-1616486029423-aaa4789e8c9a','Natural textures in a considered interior')],
              'travel':[('photo-1470770841072-f978cf4d019e','Quiet mountain lake beneath a wide sky'),('photo-1464822759023-fed622ff2c3b','Mountain peaks in clear daylight'),('photo-1500530855697-b586d89ba3ee','A traveler looking out over a landscape'),('photo-1488646953014-85cb44e25828','A city street ready to explore'),('photo-1501785888041-af3ef285b470','Still water beneath distant mountains')],
              'beauty':[('photo-1608248543803-ba4f8c70ae0b','Simple skincare products in soft natural light'),('photo-1570172619644-dfd03ed5d881','A quiet spa and self-care setting'),('photo-1596462502278-27bfdc403348','A curated makeup collection'),('photo-1522335789203-aabd1fc54bc9','A person applying makeup in natural light'),('photo-1612817288484-6f916006741a','Minimal beauty products arranged on a surface')],
              'shopping':[('photo-1553062407-98eeb64c6a62','A practical travel backpack'),('photo-1542291026-7eec264c27ff','A pair of everyday athletic shoes'),('photo-1523275335684-37898b6baf30','A clean, classic wristwatch'),('photo-1526170375885-4d8ecf77b99f','A compact camera ready for a trip'),('photo-1491553895911-0055eca6402d','Well-made shoes viewed up close')],
              'technology':[('photo-1518770660439-4636190af475','A close-up of modern circuit hardware'),('photo-1519389950473-47ba0277781c','A small team collaborating around laptops'),('photo-1516321318423-f06f85e504b3','A laptop used in a bright workspace'),('photo-1517336714731-489689fd1ca8','A laptop on a clean desk'),('photo-1517430816045-df4b7de11d1d','Technology hardware and accessories')],
              'wellness':[('photo-1544367567-0f2fcb009e0b','A quiet moment of movement and stretching'),('photo-1506126613408-eca07ce68773','A person practicing mindfulness outdoors'),('photo-1571019613454-1cb2f99b2d8b','Movement and exercise in a sunlit studio'),('photo-1526506118085-60ce8714f8c5','A person preparing for a workout'),('photo-1518611012118-696072aa579a','A gentle yoga practice on a mat')]
            }
            photo_index={name:0 for name in photos}
            for title,cat,excerpt,body in samples:
                clean_title=title[8:] if title.startswith('Sample: ') else title
                cat_id=db.execute('select id from categories where slug=?',(cat,)).fetchone()['id'];slug=slugify(clean_title)
                photo_id,alt=photos[cat][photo_index[cat]%len(photos[cat])];photo_index[cat]+=1
                image=f'https://images.unsplash.com/{photo_id}?auto=format&fit=crop&w=1200&q=82'
                body=body.replace('DEMO CONTENT — ','').replace('This example is illustrative and is not reported fashion advice.\n\n','').replace('A sample lifestyle story for demonstrating the editor.\n\n','')
                body='EDITORIAL PREVIEW — Starter content for your publication. Review and customize this story before representing it as reported, reviewed, or professional advice.\n\n'+body.replace('DEMO CONTENT — ','')
                db.execute('insert or ignore into posts(title,slug,excerpt,body,status,author_id,category_id,featured,is_sample,featured_image,image_alt,image_caption,image_credit,created_at,updated_at,published_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',(clean_title,slug,excerpt,body,'published',1,cat_id,int('Considered Wardrobe' in clean_title),1,image,alt,excerpt,'Unsplash'))
                db.execute('update posts set title=?,is_sample=1,featured_image=?,image_alt=?,image_caption=?,image_credit="Unsplash",body=case when body like "EDITORIAL PREVIEW —%" then body else ?||replace(body,"DEMO CONTENT — ","") end where slug=?',(clean_title,image,alt,excerpt,'EDITORIAL PREVIEW — Starter content for your publication. Review and customize this story before representing it as reported, reviewed, or professional advice.\n\n',slug))
            db.execute("insert into settings(key,value) values('demo_seed_version','3') on conflict(key) do update set value=excluded.value")
            db.commit()
        if not db.execute("select value from settings where key='demo_published_dates_version'").fetchone():
            db.execute("update posts set published_at=date('now','-'||(1+abs(random()%90))||' days')||' '||printf('%02d:%02d:00',9+abs(random()%9),abs(random()%60)) where status='published' and is_sample=1")
            db.execute("insert into settings(key,value) values('demo_published_dates_version','1')")
            db.commit()
        if not db.execute("select value from settings where key='real_content_seed_version'").fetchone():
            from .real_content import ARTICLES
            authors_by_category={
                'fashion':('Mara Chen','mara-chen','Fashion and beauty editor covering style, textiles, and the business behind what we wear.','Fashion & Beauty Editor'),
                'beauty':('Mara Chen','mara-chen','Fashion and beauty editor covering style, textiles, and the business behind what we wear.','Fashion & Beauty Editor'),
                'travel':('Daniel Osei','daniel-osei','Travel editor who plans and fact-checks itineraries across Europe, Asia, and North America.','Travel Editor'),
                'lifestyle':('Priya Nandan','priya-nandan','Lifestyle and wellness editor focused on sustainable routines and everyday habits.','Lifestyle & Wellness Editor'),
                'wellness':('Priya Nandan','priya-nandan','Lifestyle and wellness editor focused on sustainable routines and everyday habits.','Lifestyle & Wellness Editor'),
                'shopping':('Theo Bennett','theo-bennett','Technology and shopping editor who writes buying guides and tests everyday gear.','Technology & Shopping Editor'),
                'technology':('Theo Bennett','theo-bennett','Technology and shopping editor who writes buying guides and tests everyday gear.','Technology & Shopping Editor'),
            }
            for author_name,author_slug,bio,job_title in {v for v in authors_by_category.values()}:
                db.execute('insert or ignore into authors(name,slug,bio,job_title) values(?,?,?,?)',(author_name,author_slug,bio,job_title))
            photo_pool={
                'fashion':['1483985988355-763728e1935b','1490481651871-ab68de25d43d','1515886657613-9f3515b0c78f','1529139574466-a303027c1d8b','1539109136881-3be0616acf4b'],
                'lifestyle':['1497366754035-f200968a6e72','1600210492486-724fe5c67fb0','1616486029423-aaa4789e8c9a','1616486338812-3dadae4b4ace','1618220179428-7757a8c0b2f5'],
                'travel':['1464822759023-fed622ff2c3b','1470770841072-f978cf4d019e','1488646953014-85cb44e25828','1500530855697-b586d89ba3ee','1501785888041-af3ef285b470'],
                'beauty':['1522335789203-aabd1fc54bc9','1570172619644-dfd03ed5d881','1596462502278-27bfdc403348','1608248543803-ba4f8c70ae0b','1612817288484-6f916006741a'],
                'shopping':['1491553895911-0055eca6402d','1523275335684-37898b6baf30','1526170375885-4d8ecf77b99f','1542291026-7eec264c27ff','1553062407-98eeb64c6a62'],
                'technology':['1516321318423-f06f85e504b3','1517336714731-489689fd1ca8','1517430816045-df4b7de11d1d','1518770660439-4636190af475','1519389950473-47ba0277781c'],
                'wellness':['1506126613408-eca07ce68773','1518611012118-696072aa579a','1526506118085-60ce8714f8c5','1544367567-0f2fcb009e0b','1571019613454-1cb2f99b2d8b'],
            }
            photo_index={cat:0 for cat in photo_pool}
            featured_slugs={'style-one-blazer-five-ways','4-day-kyoto-itinerary-without-crowds','skin-cycling-still-works','ai-note-taking-apps-actually-useful','zone-2-cardio-slow-workouts'}
            total=len(ARTICLES); now=datetime.now(timezone.utc)
            for i,art in enumerate(ARTICLES):
                cat_row=db.execute('select id from categories where slug=?',(art['category'],)).fetchone()
                if not cat_row: continue
                _,author_slug,_,_=authors_by_category[art['category']]
                author_row=db.execute('select id from authors where slug=?',(author_slug,)).fetchone()
                pool=photo_pool[art['category']]; photo_id=pool[photo_index[art['category']]%len(pool)]; photo_index[art['category']]+=1
                image=f'https://images.unsplash.com/photo-{photo_id}?auto=format&fit=crop&w=1200&q=82'
                days_ago=5+round((total-1-i)*(178/max(total-1,1)))
                published_dt=now-timedelta(days=days_ago,hours=(i*7)%15,minutes=(i*13)%60)
                published_at=published_dt.strftime('%Y-%m-%d %H:%M:%S')
                featured=1 if art['slug'] in featured_slugs else 0
                db.execute('insert or ignore into posts(title,slug,excerpt,body,status,author_id,category_id,featured,affiliate_disclosure,is_sample,seo_title,meta_description,featured_image,image_alt,image_caption,image_credit,created_at,updated_at,published_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(art['title'],art['slug'],art['excerpt'],art['body'],'published',author_row['id'],cat_row['id'],featured,0,0,art['seo_title'],art['meta_description'],image,art['image_alt'],art['excerpt'],'Unsplash',published_at,published_at,published_at))
                post_row=db.execute('select id from posts where slug=?',(art['slug'],)).fetchone()
                if post_row:
                    for tag_name in art['tags']:
                        tag_slug=slugify(tag_name)
                        db.execute('insert or ignore into tags(name,slug) values(?,?)',(tag_name,tag_slug))
                        tag_id=db.execute('select id from tags where slug=?',(tag_slug,)).fetchone()['id']
                        db.execute('insert or ignore into post_tags(post_id,tag_id) values(?,?)',(post_row['id'],tag_id))
            db.execute("update posts set status='draft' where is_sample=1 and status='published'")
            db.execute("insert into settings(key,value) values('real_content_seed_version','1')")
            db.commit()
def main():
    initialize_site_data()
    threading.Thread(target=scheduler,daemon=True,name='scheduled-publisher').start()
    host=os.environ.get('BEYONDTOPIC_HOST','127.0.0.1');port=int(os.environ.get('PORT','8000'))
    print(f'BeyondTopic ready at http://{host}:{port}/')
    make_server(host,port,app).serve_forever()

if __name__=='__main__':main()
