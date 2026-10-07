-- Movie posters: suggestions picked from the movie search keep their TMDB
-- poster so it can be shown next to the suggestion. Run once in Supabase.
alter table suggestions add column if not exists poster_url text;

notify pgrst, 'reload schema';
