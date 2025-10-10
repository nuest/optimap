add a button to the work landing page for the logged in admin that takes the user directly to the editing view in the Django backend.

for the article http://127.0.0.1:8000/work/10.1007/s11368-020-02742-9/ with the internal ID 949

the editing page is http://127.0.0.1:8000/admin/publications/publication/949/change/

--


expand all harvesting to identify an existing OpenAlex record based on the available unique identifier and store the OpenAlex ID together with the record; if there is no perfet match then the property of the record should be set to None and a seperate field should indicate which partial match(es) were found and what kind of match it was (e.g. DOI match, title+author match, etc);

expand all harvesting to include the messages that led to a warning log also in the email that is sent after the harvesting run, so that the user can see what went wrong without having to check the logs;

--


add feed-based harvesting support (RSS/Atom) for EarthArxiv;

all articles from EarthArxiv are available via https://eartharxiv.org/repository/list/

there is a feed at https://eartharxiv.org/feed/ but it is unclear how many articles it contains
