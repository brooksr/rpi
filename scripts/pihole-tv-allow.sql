-- Pi-hole: allow domains for the TV group (id 1) that the TV's blocklists catch
-- but the TV needs. New domains land in Default (group 0) only, which the TV
-- isn't in, so each is also added to TV. Then: sudo pihole reloadlists
INSERT OR IGNORE INTO domainlist (type, domain, comment) VALUES
  (0, 'www.samsungotn.net', 'Samsung TV software updates'),
  (0, 'api.distribution.hulu.com', 'Hulu playback');
INSERT OR IGNORE INTO domainlist_by_group (domainlist_id, group_id)
  SELECT id, 1 FROM domainlist WHERE type = 0 AND domain IN ('www.samsungotn.net', 'api.distribution.hulu.com');
SELECT d.domain, group_concat(g.group_id) FROM domainlist d JOIN domainlist_by_group g ON g.domainlist_id = d.id GROUP BY d.id;
