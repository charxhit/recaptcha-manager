
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


class BadSiteKeyError(Errors):
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


class InvalidBatchID(Errors):
    """
    Raised when the batch_id supplied to ManalManager is incorrect
    """
    pass


class RestoreError(Errors):
    """
    Raised due to an error when attempting to create or use restore points
    """
    pass


class TimeOutError(TimeoutError):
    """
    Raised when time spent waiting for a captcha inside managers exceeds the maximum allowed.
    """
    pass


class Exhausted(Errors):
    """
    Raised when managers are no longer usable
    """
    pass


class EmptyError(Errors):
    """
    Raised when no captchas are being currently solved for a specified batch_id when using ManualManagers
    """
    pass


class UnexpectedResponse(RuntimeError, Errors):
    """
    Raised when the solving service replied with an unparsable message
    """
    pass

