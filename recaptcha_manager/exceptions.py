
class Errors(Exception):
    """
    Base class for all recaptcha_manager exceptions
    """
    pass


class LowBidError(Errors):
    """
    Only for captcha services which use a bidding system. Raised when client's bid is less than captcha-service's
    current required bid
    """
    pass


class NoBalanceError(Errors):
    """
    Raised when server reports that the client's balance is insufficient
    """
    pass


class BadAPIKeyError(Errors):
    """
    Raised when server reports APIKey is incorrect
    """
    pass


class BadSitekeyError(Errors):
    """
    Raised when server reports provided sitekey is incorrect. May also signify that provided sitekey-domain combination
    is incorrect
    """
    pass


class BadDomainError(Errors):
    """
    Raised when server reports provided domain is incorrect. May also signify that provided sitekey-domain combination
    is incorrect
    """
    pass
