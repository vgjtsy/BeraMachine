import json
import random
import string
import asyncio
import traceback

import aioimaplib

from config import IMAP_CONFIG
from general_settings import TWO_CAPTCHA_API_KEY
from modules.interfaces import SoftwareExceptionWithoutRetry, SoftwareException
from utils.tools import helper
from datetime import datetime, timedelta
from modules import Logger, RequestClient
from eth_account.messages import encode_defunct
from time import time
from uuid import uuid4


class Galxe(Logger, RequestClient):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.user_info = None
        self.base_url = 'https://graphigo.prd.galaxy.eco/query'

    # async def report_captcha(self):
    #     url = 'https://2captcha.com/res.php'
    #
    #     params = {
    #         'key': TWO_CAPTCHA_API_KEY,
    #         'action': 'reportbad',
    #         'id': '244bcb8b9846215df5af4c624a750db4',
    #         'json': 1
    #     }
    #
    #     print(await self.make_request(url=url, params=params))
    #
    #     self.logger_msg(
    #         *self.client.acc_info, msg=f'Successfully requested a refund for bad solution', type_msg='success')

    async def create_task_for_captcha(self):
        url = 'https://api.2captcha.com/createTask'

        payload = {
            "clientKey": TWO_CAPTCHA_API_KEY,
            "task": {
                "type": "GeeTestTaskProxyless",
                "websiteURL": "https://galxe.com",
                "version": 4,
                "initParameters": {
                    "captcha_id": "244bcb8b9846215df5af4c624a750db4"
                }
            }
        }

        response = await self.make_request(method="POST", url=url, json=payload, module_name='Create task for captcha')

        if not response['errorId']:
            return response['taskId']
        raise SoftwareException('Bad request to 2Captcha(Create Task)')

    async def get_captcha_data(self):
        url = 'https://api.2captcha.com/getTaskResult'

        counter = 0
        while True:
            task_id = await self.create_task_for_captcha()

            payload = {
                "clientKey": TWO_CAPTCHA_API_KEY,
                "taskId": task_id
            }

            headers = {
                'content-type': 'text/plain; charset=utf-8'
            }

            # response = None
            total_time = 0
            timeout = 360
            while True:
                try:
                    response = await self.make_request(method="POST", url=url, json=payload, headers=headers)

                    if response['status'] == 'ready':
                        captcha_data = response['solution']

                        return {
                            "lotNumber": captcha_data['lot_number'],
                            "passToken": captcha_data['pass_token'],
                            "genTime": captcha_data['gen_time'],
                            "captchaOutput": captcha_data['captcha_output'],
                        }

                    total_time += 5
                    await asyncio.sleep(5)

                    if total_time > timeout:
                        raise SoftwareException('Can`t get captcha solve in 360 second')
                except KeyError:
                    counter += 1
                    if counter > 10:
                        raise SoftwareException('Can`t solve captcha in 10 tries')
                    self.logger_msg(
                        *self.client.acc_info, msg=f'Bad captcha solve from 2captcha, trying again in 30 second...',
                        type_msg='warning')
                    # if int(response.get('errorId')) != 12:
                    #     await self.report_captcha()
                    await asyncio.sleep(30)
                    break

    async def check_galxe_id_exist(self):
        payload = {
            "operationName": "GalxeIDExist",
            "variables": {
                "schema": f"EVM:{self.client.address}"
            },
            "query": "query GalxeIDExist($schema: String!) {\n  galxeIdExist(schema: $schema)\n}\n"
        }

        response = await self.make_request(method="POST", url=self.base_url, json=payload, module_name='GalxeIDExist')

        if response['data']['galxeIdExist']:
            return True
        return False

    async def sign_in(self):
        url = 'https://graphigo.prd.galaxy.eco/query'

        characters = string.ascii_letters + string.digits
        nonce = ''.join(random.choice(characters) for _ in range(17))
        current_time = datetime.utcnow()
        seven_days_later = current_time + timedelta(days=7)
        issued_time = current_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        expiration_time = seven_days_later.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        text = (f"galxe.com wants you to sign in with your Ethereum account:\n{self.client.address}\n\nSign in with"
                f" Ethereum to the app.\n\nURI: https://galxe.com\nVersion: 1\nChain ID: 1\nNonce: {nonce}\nIssued"
                f" At: {issued_time}\nExpiration Time: {expiration_time}")

        text_hex = "0x" + text.encode('utf-8').hex()
        text_encoded = encode_defunct(hexstr=text_hex)
        signature = self.client.w3.eth.account.sign_message(text_encoded, private_key=self.client.private_key).signature

        data = {
            "operationName": "SignIn",
            "variables": {
                "input": {
                    "address": self.client.address,
                    "message": text,
                    "signature": signature.hex(),
                    "addressType": "EVM"
                }
            },
            "query": "mutation SignIn($input: Auth) {\n  signin(input: $input)\n}\n"
        }

        response = await self.make_request(method="POST", url=url, json=data, module_name='SignIn')

        self.client.session.headers.update(
            {
                'Authorization': response['data']['signin']
            }
        )

        return True

    async def get_cred_id(self):
        payload = {
            "operationName": "CampaignDetailAll",
            "variables": {
                "address": self.client.address,
                "id": "GCTN3ttM4T",
                "withAddress": True
            },
            "query": "query CampaignDetailAll($id: ID!, $address: String!, $withAddress: Boolean!) {\n  campaign(id: $id) {\n    ...CampaignForSiblingSlide\n    coHostSpaces {\n      ...SpaceDetail\n      isAdmin(address: $address) @include(if: $withAddress)\n      isFollowing @include(if: $withAddress)\n      followersCount\n      categories\n      __typename\n    }\n    bannerUrl\n    ...CampaignDetailFrag\n    userParticipants(address: $address, first: 1) @include(if: $withAddress) {\n      list {\n        status\n        premintTo\n        __typename\n      }\n      __typename\n    }\n    space {\n      ...SpaceDetail\n      isAdmin(address: $address) @include(if: $withAddress)\n      isFollowing @include(if: $withAddress)\n      followersCount\n      categories\n      __typename\n    }\n    isBookmarked(address: $address) @include(if: $withAddress)\n    inWatchList\n    claimedLoyaltyPoints(address: $address) @include(if: $withAddress)\n    parentCampaign {\n      id\n      isSequencial\n      thumbnail\n      __typename\n    }\n    isSequencial\n    numNFTMinted\n    childrenCampaigns {\n      ...ChildrenCampaignsForCampaignDetailAll\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment CampaignDetailFrag on Campaign {\n  id\n  ...CampaignMedia\n  ...CampaignForgePage\n  ...CampaignForCampaignParticipantsBox\n  name\n  numberID\n  type\n  inWatchList\n  cap\n  info\n  useCred\n  smartbalancePreCheck(mintCount: 1)\n  smartbalanceDeposited\n  formula\n  status\n  seoImage\n  creator\n  tags\n  thumbnail\n  gasType\n  isPrivate\n  createdAt\n  requirementInfo\n  description\n  enableWhitelist\n  chain\n  startTime\n  endTime\n  requireEmail\n  requireUsername\n  blacklistCountryCodes\n  whitelistRegions\n  rewardType\n  distributionType\n  rewardName\n  claimEndTime\n  loyaltyPoints\n  tokenRewardContract {\n    id\n    address\n    chain\n    __typename\n  }\n  tokenReward {\n    userTokenAmount\n    tokenAddress\n    depositedTokenAmount\n    tokenRewardId\n    tokenDecimal\n    tokenLogo\n    tokenSymbol\n    __typename\n  }\n  nftHolderSnapshot {\n    holderSnapshotBlock\n    __typename\n  }\n  spaceStation {\n    id\n    address\n    chain\n    __typename\n  }\n  ...WhitelistInfoFrag\n  ...WhitelistSubgraphFrag\n  gamification {\n    ...GamificationDetailFrag\n    __typename\n  }\n  creds {\n    id\n    name\n    type\n    credType\n    credSource\n    referenceLink\n    description\n    lastUpdate\n    lastSync\n    syncStatus\n    credContractNFTHolder {\n      timestamp\n      __typename\n    }\n    chain\n    eligible(address: $address, campaignId: $id)\n    subgraph {\n      endpoint\n      query\n      expression\n      __typename\n    }\n    dimensionConfig\n    value {\n      gitcoinPassport {\n        score\n        lastScoreTimestamp\n        __typename\n      }\n      __typename\n    }\n    commonInfo {\n      participateEndTime\n      modificationInfo\n      __typename\n    }\n    __typename\n  }\n  credentialGroups(address: $address) {\n    ...CredentialGroupForAddress\n    __typename\n  }\n  rewardInfo {\n    discordRole {\n      guildId\n      guildName\n      roleId\n      roleName\n      inviteLink\n      __typename\n    }\n    premint {\n      startTime\n      endTime\n      chain\n      price\n      totalSupply\n      contractAddress\n      banner\n      __typename\n    }\n    loyaltyPoints {\n      points\n      __typename\n    }\n    loyaltyPointsMysteryBox {\n      points\n      weight\n      __typename\n    }\n    __typename\n  }\n  participants {\n    participantsCount\n    bountyWinnersCount\n    __typename\n  }\n  taskConfig(address: $address) {\n    participateCondition {\n      conditions {\n        ...ExpressionEntity\n        __typename\n      }\n      conditionalFormula\n      eligible\n      __typename\n    }\n    rewardConfigs {\n      id\n      conditions {\n        ...ExpressionEntity\n        __typename\n      }\n      conditionalFormula\n      description\n      rewards {\n        ...ExpressionReward\n        __typename\n      }\n      eligible\n      rewardAttrVals {\n        attrName\n        attrTitle\n        attrVal\n        __typename\n      }\n      __typename\n    }\n    referralConfig {\n      id\n      conditions {\n        ...ExpressionEntity\n        __typename\n      }\n      conditionalFormula\n      description\n      rewards {\n        ...ExpressionReward\n        __typename\n      }\n      eligible\n      rewardAttrVals {\n        attrName\n        attrTitle\n        attrVal\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  referralCode(address: $address)\n  recurringType\n  latestRecurringTime\n  nftTemplates {\n    id\n    image\n    treasureBack\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignMedia on Campaign {\n  thumbnail\n  rewardName\n  type\n  gamification {\n    id\n    type\n    __typename\n  }\n  __typename\n}\n\nfragment CredentialGroupForAddress on CredentialGroup {\n  id\n  description\n  credentials {\n    ...CredForAddressWithoutMetadata\n    __typename\n  }\n  conditionRelation\n  conditions {\n    expression\n    eligible\n    ...CredentialGroupConditionForVerifyButton\n    __typename\n  }\n  rewards {\n    expression\n    eligible\n    rewardCount\n    rewardType\n    __typename\n  }\n  rewardAttrVals {\n    attrName\n    attrTitle\n    attrVal\n    __typename\n  }\n  claimedLoyaltyPoints\n  __typename\n}\n\nfragment CredForAddressWithoutMetadata on Cred {\n  id\n  name\n  type\n  credType\n  credSource\n  referenceLink\n  description\n  lastUpdate\n  lastSync\n  syncStatus\n  credContractNFTHolder {\n    timestamp\n    __typename\n  }\n  chain\n  eligible(address: $address)\n  subgraph {\n    endpoint\n    query\n    expression\n    __typename\n  }\n  dimensionConfig\n  value {\n    gitcoinPassport {\n      score\n      lastScoreTimestamp\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment CredentialGroupConditionForVerifyButton on CredentialGroupCondition {\n  expression\n  eligibleAddress\n  __typename\n}\n\nfragment WhitelistInfoFrag on Campaign {\n  id\n  whitelistInfo(address: $address) {\n    address\n    maxCount\n    usedCount\n    claimedLoyaltyPoints\n    currentPeriodClaimedLoyaltyPoints\n    currentPeriodMaxLoyaltyPoints\n    __typename\n  }\n  __typename\n}\n\nfragment WhitelistSubgraphFrag on Campaign {\n  id\n  whitelistSubgraph {\n    query\n    endpoint\n    expression\n    variable\n    __typename\n  }\n  __typename\n}\n\nfragment GamificationDetailFrag on Gamification {\n  id\n  type\n  nfts {\n    nft {\n      id\n      animationURL\n      category\n      powah\n      image\n      name\n      treasureBack\n      nftCore {\n        ...NftCoreInfoFrag\n        __typename\n      }\n      traits {\n        name\n        value\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  airdrop {\n    name\n    contractAddress\n    token {\n      address\n      icon\n      symbol\n      __typename\n    }\n    merkleTreeUrl\n    addressInfo(address: $address) {\n      index\n      amount {\n        amount\n        ether\n        __typename\n      }\n      proofs\n      __typename\n    }\n    __typename\n  }\n  forgeConfig {\n    minNFTCount\n    maxNFTCount\n    requiredNFTs {\n      nft {\n        category\n        powah\n        image\n        name\n        nftCore {\n          capable\n          contractAddress\n          __typename\n        }\n        __typename\n      }\n      count\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment NftCoreInfoFrag on NFTCore {\n  id\n  capable\n  chain\n  contractAddress\n  name\n  symbol\n  dao {\n    id\n    name\n    logo\n    alias\n    __typename\n  }\n  __typename\n}\n\nfragment ExpressionEntity on ExprEntity {\n  cred {\n    id\n    name\n    type\n    credType\n    credSource\n    dimensionConfig\n    referenceLink\n    description\n    lastUpdate\n    lastSync\n    chain\n    eligible(address: $address)\n    metadata {\n      visitLink {\n        link\n        __typename\n      }\n      twitter {\n        isAuthentic\n        __typename\n      }\n      __typename\n    }\n    commonInfo {\n      participateEndTime\n      modificationInfo\n      __typename\n    }\n    __typename\n  }\n  attrs {\n    attrName\n    operatorSymbol\n    targetValue\n    __typename\n  }\n  attrFormula\n  eligible\n  eligibleAddress\n  __typename\n}\n\nfragment ExpressionReward on ExprReward {\n  arithmetics {\n    ...ExpressionEntity\n    __typename\n  }\n  arithmeticFormula\n  rewardType\n  rewardCount\n  rewardVal\n  __typename\n}\n\nfragment CampaignForgePage on Campaign {\n  id\n  numberID\n  chain\n  spaceStation {\n    address\n    __typename\n  }\n  gamification {\n    forgeConfig {\n      maxNFTCount\n      minNFTCount\n      requiredNFTs {\n        nft {\n          category\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForCampaignParticipantsBox on Campaign {\n  ...CampaignForParticipantsDialog\n  id\n  chain\n  space {\n    id\n    isAdmin(address: $address)\n    __typename\n  }\n  participants {\n    participants(first: 10, after: \"-1\", download: false) {\n      list {\n        address {\n          id\n          avatar\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    participantsCount\n    bountyWinners(first: 10, after: \"-1\", download: false) {\n      list {\n        createdTime\n        address {\n          id\n          avatar\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    bountyWinnersCount\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForParticipantsDialog on Campaign {\n  id\n  name\n  type\n  rewardType\n  chain\n  nftHolderSnapshot {\n    holderSnapshotBlock\n    __typename\n  }\n  space {\n    isAdmin(address: $address)\n    __typename\n  }\n  rewardInfo {\n    discordRole {\n      guildName\n      roleName\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment SpaceDetail on Space {\n  id\n  name\n  info\n  thumbnail\n  alias\n  status\n  links\n  isVerified\n  discordGuildID\n  followersCount\n  nftCores(input: {first: 1}) {\n    list {\n      id\n      marketLink\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment ChildrenCampaignsForCampaignDetailAll on Campaign {\n  space {\n    ...SpaceDetail\n    isAdmin(address: $address) @include(if: $withAddress)\n    isFollowing @include(if: $withAddress)\n    followersCount\n    categories\n    __typename\n  }\n  ...CampaignDetailFrag\n  claimedLoyaltyPoints(address: $address) @include(if: $withAddress)\n  userParticipants(address: $address, first: 1) @include(if: $withAddress) {\n    list {\n      status\n      __typename\n    }\n    __typename\n  }\n  parentCampaign {\n    id\n    isSequencial\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForSiblingSlide on Campaign {\n  id\n  space {\n    id\n    alias\n    __typename\n  }\n  parentCampaign {\n    id\n    thumbnail\n    isSequencial\n    childrenCampaigns {\n      id\n      ...CampaignForGetImage\n      ...CampaignForCheckFinish\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForCheckFinish on Campaign {\n  claimedLoyaltyPoints(address: $address)\n  whitelistInfo(address: $address) {\n    usedCount\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForGetImage on Campaign {\n  ...GetImageCommon\n  nftTemplates {\n    image\n    __typename\n  }\n  __typename\n}\n\nfragment GetImageCommon on Campaign {\n  ...CampaignForTokenObject\n  id\n  type\n  thumbnail\n  __typename\n}\n\nfragment CampaignForTokenObject on Campaign {\n  tokenReward {\n    tokenAddress\n    tokenSymbol\n    tokenDecimal\n    tokenLogo\n    __typename\n  }\n  tokenRewardContract {\n    id\n    chain\n    __typename\n  }\n  __typename\n}\n"
        }

        response = await self.make_request(method="POST", url=self.base_url, json=payload,
                                           module_name='CampaignDetailAll')

        return response['data']['campaign']['credentialGroups'][0]['credentials'][0]['id']

    async def check_and_get_nickname(self):
        url = 'https://plarium.com/services/api/nicknames/new/create?group=2&gender=2'

        while True:
            response = await self.make_request(method='POST', url=url)

            nickname = f"{random.choice(list(response))}{random.randint(1000, 10000)}"

            payload = {
                "operationName": "IsUsernameExisting",
                "variables": {
                    "username": nickname
                },
                "query": "query IsUsernameExisting($username: String!) {\n  usernameExist(username: $username)\n}\n"
            }

            response = await self.make_request(method="POST", url=self.base_url, json=payload,
                                               module_name='Check nickname')

            if not response['data']['usernameExist']:
                return nickname

    async def create_new_acc(self):
        nickname = await self.check_and_get_nickname()

        payload = {
            "operationName": "CreateNewAccount",
            "variables": {
                "input": {
                    "schema": f"EVM:{self.client.address}",
                    "socialUsername": "",
                    "username": nickname
                }
            },
            "query": "mutation CreateNewAccount($input: CreateNewAccount!) {\n  createNewAccount(input: $input)\n}\n"
        }

        await self.make_request(method="POST", url=self.base_url, json=payload, module_name='CreateNewAccount')

        self.logger_msg(
            *self.client.acc_info,
            msg=f"Successfully registered on Galxe with nickname: {nickname}", type_msg='success')

        return True

    async def get_user_info(self):
        payload = {
            "operationName": "BasicUserInfo",
            "variables": {
                "address": self.client.address
            },
            "query": "query BasicUserInfo($address: String!) {\n  addressInfo(address: $address) {\n"
                     "    id\n    username\n    avatar\n    address\n    evmAddressSecondary {\n"
                     "      address\n      __typename\n    }\n    hasEmail\n    solanaAddress\n"
                     "    aptosAddress\n    seiAddress\n    injectiveAddress\n    flowAddress\n"
                     "    starknetAddress\n    bitcoinAddress\n    hasEvmAddress\n"
                     "    hasSolanaAddress\n    hasAptosAddress\n    hasInjectiveAddress\n    hasFlowAddress\n"
                     "    hasStarknetAddress\n    hasBitcoinAddress\n    hasTwitter\n    hasGithub\n"
                     "    hasDiscord\n    hasTelegram\n    displayEmail\n    displayTwitter\n"
                     "    displayGithub\n    displayDiscord\n    displayTelegram\n    displayNamePref\n"
                     "    email\n    twitterUserID\n    twitterUserName\n    githubUserID\n    githubUserName\n"
                     "    discordUserID\n    discordUserName\n    telegramUserID\n    telegramUserName\n"
                     "    enableEmailSubs\n    subscriptions\n    isWhitelisted\n    isInvited\n    isAdmin\n"
                     "    accessToken\n    __typename\n  }\n}\n"
        }

        response = await self.make_request(method="POST", url=self.base_url, json=payload, module_name='BasicUserInfo')
        return response['data']['addressInfo']

    async def send_email(self):
        payload = {
            "operationName": "SendVerifyCode",
            "variables": {
                "input": {
                    "address": self.client.address,
                    "email": self.client.email_address,
                    "captcha": await self.get_captcha_data()
                }
            },
            "query": "mutation SendVerifyCode($input: SendVerificationEmailInput!) {\n  sendVerificationCode(input: $input) {\n    code\n    message\n    __typename\n  }\n}\n"
        }

        await self.make_request(method="POST", url=self.base_url, json=payload, module_name='SendVerifyCode')

        self.logger_msg(
            *self.client.acc_info, msg=f"Successfully send verification code to {self.client.email_address}",
            type_msg='success')

    async def confirm_email(self, code: str):
        while True:
            payload = {
                "operationName": "UpdateEmail",
                "variables": {
                    "input": {
                        "address": self.client.address,
                        "email": self.client.email_address,
                        "verificationCode": code
                    }
                },
                "query": "mutation UpdateEmail($input: UpdateEmailInput!) {\n  updateEmail(input: $input) {\n    code\n    message\n    __typename\n  }\n}\n"
            }

            await self.make_request(method="POST", url=self.base_url, json=payload, module_name='UpdateEmail')

            return True

    async def reload_task(self, cred_id):

        payload = {
            "operationName": "SyncCredentialValue",
            "variables": {
                "input": {
                    "syncOptions": {
                        "address": self.client.address,
                        "credId": f"{cred_id}",
                    }
                }
            },
            "query": "mutation SyncCredentialValue($input: SyncCredentialValueInput!) {\n  syncCredentialValue(input: $input) {\n    value {\n      address\n      spaceUsers {\n        follow\n        points\n        participations\n        __typename\n      }\n      campaignReferral {\n        count\n        __typename\n      }\n      gitcoinPassport {\n        score\n        lastScoreTimestamp\n        __typename\n      }\n      walletBalance {\n        balance\n        __typename\n      }\n      multiDimension {\n        value\n        __typename\n      }\n      allow\n      survey {\n        answers\n        __typename\n      }\n      quiz {\n        allow\n        correct\n        __typename\n      }\n      __typename\n    }\n    message\n    __typename\n  }\n}\n"
        }

        response = await self.make_request(method="POST", url=self.base_url, json=payload,
                                           module_name='SyncCredentialValue')

        if response['data']['syncCredentialValue']['value']['allow']:
            return True
        return False

    async def claim_points(self):
        payload = {
            "operationName": "PrepareParticipate",
            "variables": {
                "input": {
                    "address": self.client.address,
                    "campaignID": "GCTN3ttM4T",
                    "captcha": await self.get_captcha_data(),
                    "chain": "ETHEREUM",
                    "mintCount": 1,
                    "signature": ""
                }
            },
            "query": "mutation PrepareParticipate($input: PrepareParticipateInput!) {\n"
                     "  prepareParticipate(input: $input) {\n    allow\n    disallowReason\n    signature\n    nonce\n"
                     "    mintFuncInfo {\n      funcName\n      nftCoreAddress\n      verifyIDs\n      powahs\n"
                     "      cap\n      __typename\n    }\n    extLinkResp {\n      success\n      data\n      error\n"
                     "      __typename\n    }\n    metaTxResp {\n      metaSig2\n      autoTaskUrl\n"
                     "      metaSpaceAddr\n      forwarderAddr\n      metaTxHash\n      reqQueueing\n"
                     "      __typename\n    }\n    solanaTxResp {\n      mint\n      updateAuthority\n"
                     "      explorerUrl\n      signedTx\n      verifyID\n      __typename\n    }\n    aptosTxResp {\n"
                     "      signatureExpiredAt\n      tokenName\n      __typename\n    }\n    tokenRewardCampaignTxResp"
                     " {\n      signatureExpiredAt\n      verifyID\n      __typename\n    }\n    loyaltyPointsTxResp"
                     " {\n      TotalClaimedPoints\n      __typename\n    }\n    flowTxResp {\n      Name\n"
                     "      Description\n      Thumbnail\n      __typename\n    }\n    __typename\n  }\n}\n"
        }

        response = await self.make_request(method="POST", url=self.base_url, json=payload)

        if not response['data']['prepareParticipate']['loyaltyPointsTxResp']:
            self.logger_msg(*self.client.acc_info, msg=f"Already claimed points on Galxe")
        elif response['data']['prepareParticipate']['disallowReason'] != "":
            error = response['data']['prepareParticipate']['disallowReason']
            raise SoftwareException(f"Can`t claim points on Galxe. Error: {error}")

        elif int(response['data']['prepareParticipate']['loyaltyPointsTxResp']['TotalClaimedPoints']):
            points = int(response['data']['prepareParticipate']['loyaltyPointsTxResp']['TotalClaimedPoints'])
            self.logger_msg(
                *self.client.acc_info, msg=f"Successfully claim {points} points on Galxe", type_msg='success')

    async def get_gcaptcha4_data(self):

        url = 'https://gcaptcha4.geetest.com/load'

        callback = f"geetest_{round(time() * 1000)}"

        params = {
            'captcha_id': '244bcb8b9846215df5af4c624a750db4',
            'challenge': f"{uuid4()}",
            'client_type': 'web',
            'lang': 'ru',
            'callback': callback,
        }

        async with self.client.session.request(method='GET', url=url, params=params) as response:
            return (json.loads((await response.text()).split(f"{callback}(")[1][:-1]))['data']

    # async def get_captcha_data(self):
    #     url = 'https://gcaptcha4.geetest.com/verify'
    #
    #     captcha_data = await self.get_gcaptcha4_data()
    #
    #     callback = f"geetest_{round(time() * 1000)}"
    #
    #     params = {
    #         "callback": callback,
    #         "captcha_id": "244bcb8b9846215df5af4c624a750db4",
    #         "client_type": "web",
    #         "lot_number": captcha_data['lot_number'],
    #         "payload": captcha_data['payload'],
    #         "process_token": captcha_data['process_token'],
    #         "payload_protocol": "1",
    #         "pt": "1",
    #         "w": '993c7e27cd5f1b1df9e6e87a5b614297949138115a2785fd180574035d19e969be90bce9d785db24c19a94e1555d8bde29750fd912d26af9ce7d7052f979d48e13fc2b5584ff72f89cd8015fca83126115ca627aac0e02ec5849081a72468a16ffb359df04b7398ea97c79386de8a25bb332b743f6d984d3bb6b39edbf13d0443c19d40b95327f4556d2928e9068ec37ebc63358f1086f7bd461364757aefecc84bf4860a6a7f06ca6406bdac3a3bd9b80c6f1092a525eb5360e5e0aecf4f295d614d8bd1e0f375bb7ab0eee545905393093252dcfe17f9e4b4b738843d1fecf9553d0e601c9b5bdab2b87a625ed6db63118eee83df323ef6eb46cf4218c385255ea13a20d3f08d2ebd7fedf28f72ea820630832b196711145fe0b8fb24701c63f3e7976869ade6d363e18dc4d8bdc5075ab6d9ab2f6dc08ded9b0fc59a7186528dcfa9d2c33257b541d11b1b12f72329a3e7b34d5ad177fe93340278286077d76289d5e29215b4f19244a604dc1f7b7c31dfca1f50ec42d46322534f27e6eb2373b1ed1190697dd938cdef3580bac3ea20318b0d6ce510c8ce341b281460abc4565495e024a657f4b2364fff34a2eca75f3f0508a1a5bcb42be6b4285ae5c0e29f6d2643997df949894e098bfd85dd51599cf68eae460057a7628f05fcecbbf3ec1adb7ada6d285409a9f38627704982cffdb59e7a466440d953266edecd620',
    #     }
    #
    #     async with self.client.session.request(method='GET', url=url, params=params) as response:
    #         verify_data = (json.loads((await response.text()).split(f"{callback}(")[1][:-1]))['data']['seccode']
    #
    #     return {
    #         "lotNumber": verify_data['lot_number'],
    #         "passToken": verify_data['pass_token'],
    #         "genTime": verify_data['gen_time'],
    #         "captchaOutput": verify_data['captcha_output'],
    #     }
    #
    async def click_faucet_quest(self):
        url = 'https://graphigo.prd.galaxy.eco/query'

        payload = {
            "operationName": "AddTypedCredentialItems",
            "variables": {
                "input": {
                    "campaignId": "GCTN3ttM4T",
                    "captcha": await self.get_captcha_data(),
                    "credId": "380124126053949440",
                    "items": [
                        self.client.address
                    ],
                    "operation": "APPEND"
                }
            },
            "query": "mutation AddTypedCredentialItems($input: MutateTypedCredItemInput!) {\n"
                     "  typedCredentialItems(input: $input) {\n    id\n    __typename\n  }\n}\n"
        }

        await self.make_request(method="POST", url=url, json=payload)

        self.logger_msg(*self.client.acc_info, msg=f"Successfully click faucet quest on Galxe", type_msg='success')

    async def get_email_code(self):
        from email import message_from_bytes
        from bs4 import BeautifulSoup

        self.logger_msg(*self.client.acc_info, msg=f"Started searching for messages from Galxe...")

        total_time = 0
        timeout = 600
        domain_name = self.client.email_address.split('@')[-1]
        while True:
            rambler_client = aioimaplib.IMAP4_SSL(IMAP_CONFIG.get(domain_name, f'imap.{domain_name}'))

            #await rambler_client.wait_hello_from_server()
            await rambler_client.login(self.client.email_address, self.client.email_password)

            try:
                res, data = await rambler_client.select()
                try:
                    last_message_number = data[2].decode().split()[0]
                except:
                    last_message_number = data[0].decode().split()[0]

                message = await rambler_client.fetch(f"{last_message_number}", '(RFC822)')
                try:
                    message_content = message[1][1]
                except:
                    try:
                        message_content = message[1][0]
                    except:
                        message_content = message[1]

                message = message_from_bytes(message_content)

                soup = BeautifulSoup(message.as_string(), 'html.parser')

                try:
                    return soup.find('h1').text
                except:
                    total_time += 30
                    await asyncio.sleep(30)
                    if total_time > timeout:
                        break
                    continue
            except Exception as error:
                traceback.print_exc()
                self.logger_msg(
                    *self.client.acc_info, msg=f"Error in <get_email_code> function: {error}", type_msg='warning')
                total_time += 60
                await asyncio.sleep(10)
                if total_time > timeout:
                    traceback.print_exc()
                    raise SoftwareExceptionWithoutRetry('Can`t get confirmation code from email!')
                continue

    @helper
    async def claim_galxe_points_berachain_faucet(self):

        self.logger_msg(*self.client.acc_info, msg=f"Check previous registration on Galxe")

        user_exist = await self.check_galxe_id_exist()
        await self.sign_in()

        if not user_exist:
            self.logger_msg(*self.client.acc_info, msg=f"New user on Galxe, make registration")
            await self.create_new_acc()
        else:
            self.logger_msg(*self.client.acc_info, msg=f"Already registered on Galxe", type_msg='success')

        user_info = await self.get_user_info()
        if not user_info['hasEmail']:
            self.logger_msg(*self.client.acc_info, msg=f"Email is not linked to the Galxe account. Start linking...")
            await asyncio.sleep(5)
            await self.send_email()
            while True:
                code = await self.get_email_code()
                self.logger_msg(
                    *self.client.acc_info, msg=f"Successfully found a message from Galxe", type_msg='success')
                if await self.confirm_email(code):
                    break

                self.logger_msg(
                    *self.client.acc_info, msg=f"This code was wrong, will try again in 60 seconds...",
                    type_msg='warning')

                await asyncio.sleep(60)

            self.logger_msg(*self.client.acc_info, msg=f"Successfully linked mail to Galxe", type_msg='success')

        self.logger_msg(*self.client.acc_info, msg=f"Check access to complete a quest")

        cred_id = await self.get_cred_id()

        await self.click_faucet_quest()

        while True:
            if await self.reload_task(cred_id):
                break
            await asyncio.sleep(60)

        self.logger_msg(*self.client.acc_info, msg=f"Task is ready to claim points", type_msg='success')

        await self.claim_points()

        return True
