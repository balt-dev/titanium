import pytumblr
import auth

def main():
    client = pytumblr.TumblrRestClient(
        auth.CONSUMER_KEY,
        auth.CONSUMER_SECRET,
        auth.OAUTH_TOKEN,
        auth.OAUTH_SECRET
    )

    

if __name__ == "__main__":
    main()